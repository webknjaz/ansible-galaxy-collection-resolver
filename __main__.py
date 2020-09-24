from collections import namedtuple
from operator import attrgetter
from pathlib import Path
from tempfile import TemporaryDirectory

import ansible.constants as C
from ansible import context
from ansible.galaxy import Galaxy
from ansible.galaxy.api import CollectionVersionMetadata, GalaxyAPI
from ansible.galaxy.collection import CollectionRequirement

from resolvelib import AbstractProvider, BaseReporter, Resolver


# NOTE: "src" and "type" fields are reserved for future use.
# NOTE: They are currently unused because the code ignores non-Galaxy
# NOTE: locations.
Requirement = namedtuple('Requirement', ('fqcn', 'ver', 'src', 'type'))
# ^ abstract requirement

Candidate = namedtuple('Candidate', ('fqcn', 'ver', 'src', 'type'))
# ^ concrete requirement


class AnsibleGalaxyProvider(AbstractProvider):
    """Delegate class providing requirement interface for the resolver.
    """

    def __init__(self, api: GalaxyAPI):
        """Initialize helper attributes.

        :param api: An instance of the Galaxy API wrapper
        :type api: GalaxyAPI
        """
        self._api = api

    def identify(self, requirement_or_candidate):
        """Given a requirement or candidate, return an identifier for it.

        This is used to identify a requirement or candidate, e.g.
        whether two requirements should have their specifier parts
        merged, whether two candidates would conflict with each other
        (because they have same name but different versions).
        """
        return requirement_or_candidate.fqcn

    def get_preference(self, resolution, candidates, information):
        """Produce a sort key function return value for given requirement based on preference.

        FIXME: figure out the sort key
        The preference is defined as "I think this requirement should be
        resolved first". The lower the return value is, the more preferred
        this group of arguments is.
        :param resolution: Currently pinned candidate, or `None`.
        :param candidates: A list of possible candidates.
        :param information: A list of requirement information.
        Each information instance is a named tuple with two entries:
        * `requirement` specifies a requirement contributing to the current
          candidate list
        * `parent` specifies the candidate that provides (dependend on) the
          requirement, or `None` to indicate a root requirement.
        The preference could depend on a various of issues, including (not
        necessarily in this order):
        * Is this package pinned in the current resolution result?
        * How relaxed is the requirement? Stricter ones should probably be
          worked on first? (I don't know, actually.)
        * How many possibilities are there to satisfy this requirement? Those
          with few left should likely be worked on first, I guess?
        * Are there any known conflicts for this requirement? We should
          probably work on those with the most known conflicts.
        A sortable value should be returned (this will be used as the `key`
        parameter of the built-in sorting function). The smaller the value is,
        the more preferred this requirement is (i.e. the sorting function
        is called with `reverse=False`).
        """
        # NOTE: this mirrors the pip's current implementation
        # FIXME: Invent something better
        return len(candidates)

    def find_matches(self, requirements):
        """Find all possible candidates that satisfy the given requirements.

        This should try to get candidates based on the requirements' types.
        For VCS, local, and archive requirements, the one-and-only match is
        returned, and for a "named" requirement, the index(es) should be
        consulted to find concrete candidates for this requirement.
        :param requirements: A collection of requirements which all of the
            returned candidates must match. All requirements are guaranteed to
            have the same identifier. The collection is never empty.
        :returns: An iterable that orders candidates by preference, e.g. the
            most preferred candidate should come first.
        """
        assert requirements, 'Broken contract of having non-empty requirements'

        fqcn = requirements[0].fqcn
        # The fqcn is guaranteed to be the same
        namespace, name = fqcn.split('.')
        coll_versions = self._api.get_collection_versions(namespace, name)
        return sorted(
            set(
                candidate for candidate in (
                    Candidate(fqcn, version, None, None)
                    for version in coll_versions
                )
                for requirement in requirements
                if self.is_satisfied_by(requirement, candidate)
            ),
            key=attrgetter('ver'),
            reverse=True,  # prefer newer versions over older ones
        )

    def is_satisfied_by(self, requirement, candidate):
        """Whether the given requirement can be satisfied by a candidate.
        The candidate is guarenteed to have been generated from the
        requirement.
        A boolean should be returned to indicate whether `candidate` is a
        viable solution to the requirement.
        """
        return CollectionRequirement._meets_requirements(
            None,
            version=candidate.ver,
            requirements=requirement.ver,
            parent=None,
        )

    def get_dependencies(self, candidate):
        r"""Get dependencies of a candidate.

        :returns: A collection of requirements that `candidate` \
                  specifies as its dependencies.
        :rtype: list[Candidate]
        """
        namespace, name = candidate.fqcn.split('.')

        deps = (
            self._api.
            get_collection_version_metadata(namespace, name, candidate.ver).
            dependencies
        )

        return [
            Requirement(dep_name, dep_req, None, None)
            for dep_name, dep_req in deps.items()
        ]


collection_requirements = [Requirement('amazon.aws', '*', None, None)]
#collection_requirements = [Requirement('amazon.aws', '1.2.0', None, None)]
#collection_requirements = [Requirement('amazon.aws', '1.2.1-dev3', None, None)]
print()
print('Given collection requirements:')
#print(f'{collection_requirements=}')
for abstract_req in collection_requirements:
    print(f'\t* {abstract_req.fqcn}\t"{abstract_req.ver}"')
print()

context.CLIARGS = {  # patch a value normally populated by the CLI
    'ignore_certs': False,
    'type': 'collection',
}
galaxy_api = GalaxyAPI(Galaxy(), 'default_galaxy', C.GALAXY_SERVER)
resolver = Resolver(
    AnsibleGalaxyProvider(api=galaxy_api),
    BaseReporter(),
)
print()
print('Computing the dependency tree...')
print()
concrete_requirements = resolver.resolve(
    collection_requirements,
    max_rounds=2_000_000,  # avoid too deep backtracking; taken from pip
)
print()
print('Resolved concrete transitive dependencies:')
#print(f'{concrete_requirements=}')
#print(f'{concrete_requirements.mapping=}')
for coll_name, concrete_pin in concrete_requirements.mapping.items():
    print(f'\t* {coll_name}\t"{concrete_pin.ver}"')
print()

dependency_tree = concrete_requirements.graph
print()
print('Dependency tree:')
#print(f'{dependency_tree=}')
for dep_origin, dep in dependency_tree.iter_edges():
    print(f'\t* {dep_origin}\t→\t{dep}')
print()


print()
target_path = Path('./ans_coll/').resolve().absolute()
print('Attempting to install the resolved dependencies into {target_path!s}...')
print()
with TemporaryDirectory() as tmp_dir:
    for concrete_coll_pin in concrete_requirements.mapping.values():
        print(f'Installing {concrete_coll_pin.fqcn}...')
        coll_ns, coll_name = concrete_coll_pin.fqcn.split('.')
        coll_meta = galaxy_api.get_collection_version_metadata(
            namespace=coll_ns,
            name=coll_name,
            version=concrete_coll_pin.ver,
        )
        coll_meta.dependencies = {}  # we shouldn't care about deps here
        CollectionRequirement(
            namespace=coll_ns,
            name=coll_name,
            b_path=None,
            api=galaxy_api,
            versions=[concrete_coll_pin.ver],
            requirement=concrete_coll_pin.ver,
            force=False,
            allow_pre_releases=True,  # amazon.aws only has pre-releases
            metadata=coll_meta,
        ).install(
            path=target_path,
            b_temp_path=tmp_dir.encode(),
        )
        print(f'`{concrete_coll_pin.fqcn}` installed successfully.')
print()
