# ansible-galaxy-collection-resolver PoC

This is a repo demonstrating the use of the new pip resolver for
taking care of Ansible Collections dependencies resolution.

Please do not expect any further updates in this project. It is
now archived and will be kept as is for history.

## Now what?

This project has served its purpose of demonstrating that it's
quite possible to integrate [resolvelib] into `ansible-galaxy
collection` CLI.

The actual refactoring and integration work was done in
https://github.com/ansible/ansible/pull/72591 and is now complete
and merged into ansible/ansible@devel — it will be shipped with
`pip install ansible-core>=2.11`.

Read the full story @
https://webknjaz.me/prose/ansible-galaxy-reuses-pips-resolvelib/

[resolvelib]: https://github.com/sarugaku/resolvelib
