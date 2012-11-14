#!/usr/bin/python

"""
Just a little script to report on the status of bugs slated against a given 
release.

Before running this, make sure that you have set your username in 
~/.bugzillarc:

[bugzilla.redhat.com]
user = someone@redhat.com

and that you have obtained a Bugzilla session cookie by executing:

$ bugzilla login
"""

BUGZILLA_URL = 'https://bugzilla.redhat.com/xmlrpc.cgi'
GERRIT_HOSTNAME = 'gerrit.beaker-project.org'
GERRIT_SSH_PORT = 29418

import sys
import os
import subprocess
from itertools import chain
import simplejson as json
from optparse import OptionParser
import bugzilla # yum install python-bugzilla

# These are in Python 2.6
def any(iterable):
    for x in iterable:
        if x:
            return True
    return False
def all(iterable):
    for x in iterable:
        if not x:
            return False
    return True

def get_bugs(milestone, release):
    bz = bugzilla.Bugzilla(url=BUGZILLA_URL)
    # Make sure the user has logged themselves in properly, otherwise we might 
    # accidentally omit private bugs from the list
    assert bz.user, 'Configure your username in ~/.bugzillarc'
    assert bz._proxy.User.valid_cookie(dict(login=bz.user))['cookie_isvalid'] == 1
    criteria = {'product': 'Beaker'}
    if milestone:
        criteria['target_milestone'] = milestone
    if release:
        criteria['flag'] = ['beaker-%s+' % release]
    return bz.query(bz.build_query(**criteria))

def get_gerrit_changes(bug_ids):
    p = subprocess.Popen(['ssh',
            '-o', 'StrictHostKeyChecking=no', # work around ssh bug on RHEL5
            '-p', str(GERRIT_SSH_PORT), GERRIT_HOSTNAME,
            'gerrit', 'query', '--format=json', '--current-patch-set',
            ' OR '.join('bug:%d' % bug_id for bug_id in bug_ids)],
            stdout=subprocess.PIPE)
    stdout, _ = p.communicate()
    assert p.returncode == 0, p.returncode
    retval = []
    for line in stdout.splitlines():
        obj = json.loads(line)
        if obj.get('type') == 'stats':
            continue
        retval.append(obj)
    return retval

def changes_for_bug(changes, bug_id):
    for change in changes:
        change_bugs = [int(t['id']) for t in change['trackingIds'] if t['system'] == 'Bugzilla']
        if bug_id in change_bugs:
            yield change

def abbrev_user(user):
    if user.endswith('@redhat.com'):
        return user[:-len('@redhat.com')]

_revlist = None
def git_commit_reachable(sha):
    global _revlist
    if not _revlist:
        p = subprocess.Popen(['git', 'rev-list', 'HEAD'], stdout=subprocess.PIPE)
        stdout, _ = p.communicate()
        assert p.returncode == 0, p.returncode
        _revlist = stdout.splitlines()
    return sha in _revlist

def problem(message):
    if os.isatty(sys.stdout.fileno()):
        print '\033[1m\033[91m** %s\033[0m' % message
    else:
        print '** %s' % message

def main():
    parser = OptionParser('usage: %prog [options] --milestone=MILESTONE',
            description='Reports on the state of Beaker bugs for a given milestone')
    parser.add_option('-m', '--milestone', metavar='MILESTONE',
            help='Check bugs slated for MILESTONE')
    parser.add_option('-r', '--release', metavar='RELEASE',
            help='Check bugs approved for RELEASE (using flags)')
    options, args = parser.parse_args()
    if not options.milestone and not options.release:
        parser.error('Specify a milestone or release')

    bugs = get_bugs(options.milestone, options.release)
    changes = get_gerrit_changes(bug.bug_id for bug in bugs)

    for bug in sorted(bugs, key=lambda b: (b.assigned_to, b.bug_id)):
        print 'Bug %-13d %-17s %-10s <%s>' % (bug.bug_id, bug.bug_status,
                abbrev_user(bug.assigned_to), bug.url)
        bug_changes = list(changes_for_bug(changes, bug.bug_id))

        # print out summary of changes
        for change in sorted(bug_changes, key=lambda c: int(c['number'])):
            patch_set = change['currentPatchSet']
            verified = max(chain([None], (int(a['value'])
                    for a in patch_set.get('approvals', []) if a['type'] == 'VRIF'))) or 0
            reviewed = max(chain([None], (int(a['value'])
                    for a in patch_set.get('approvals', []) if a['type'] == 'CRVW'))) or 0
            print '    Change %-6s %-17s %-10s <%s>' % (change['number'],
                    '%s (%d/%d)' % (change['status'], verified, reviewed),
                    abbrev_user(change['owner']['email']), change['url'])

        # check for inconsistencies
        if bug.bug_status in ('NEW', 'ASSIGNED') and \
                any(change['status'] != 'ABANDONED' for change in bug_changes):
            if all(change['status'] == 'MERGED' for change in bug_changes):
                problem('Bug should be MODIFIED')
            else:
                problem('Bug should be POST')
        elif bug.bug_status == 'POST' and \
                not any(change['status'] == 'NEW' for change in bug_changes):
            if bug_changes and all(change['status'] == 'MERGED' for change in bug_changes):
                problem('Bug should be MODIFIED')
            else:
                problem('Bug should be ASSIGNED')
        elif bug.bug_status in ('MODIFIED', 'ON_DEV', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING', 'CLOSED'):
            if not bug_changes:
                problem('Bug should be ASSIGNED')
            elif not all(change['status'] in ('ABANDONED', 'MERGED') for change in bug_changes):
                problem('Bug should be POST')
        if options.release and bug.target_milestone != '%s.0' % options.release:
            problem('Bug target milestone should be %s.0' % options.release)
        for change in bug_changes:
            if change['status'] == 'MERGED':
                sha = change['currentPatchSet']['revision']
                if not git_commit_reachable(sha):
                    problem('Commit %s not reachable from HEAD' % sha)

        print

    if options.release:
        # check for bugs which have target milestone set but aren't approved for the release
        target_bugs = get_bugs('%s.0' % options.release, None)
        approved_bug_ids = set(b.bug_id for b in bugs)
        for unapproved in [b for b in target_bugs if b.bug_id not in approved_bug_ids]:
            print 'Bug %-13d %-17s %-10s <%s>' % (unapproved.bug_id, unapproved.bug_status,
                    abbrev_user(unapproved.assigned_to), unapproved.url)
            problem('Bug target milestone is set, but bug is not approved')
            print

if __name__ == '__main__':
    main()
