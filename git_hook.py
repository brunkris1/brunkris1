#!/usr/bin/env python

##########################################################################
# Copyright 2009 Broadcom Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License"); 
# you may not use this file except in compliance with the License. 
# You may obtain a copy of the License at 
# 
#      http://www.apache.org/licenses/LICENSE-2.0 
#
# Unless required by applicable law or agreed to in writing, software 
# distributed under the License is distributed on an "AS IS" BASIS, 
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. 
# See the License for the specific language governing permissions and 
# limitations under the License. 

# File: git-jira-hook
# Author: Joyjit Nath
#
###########################################################################

# Purpose:
# This is a git hook, to be used in an environment where git is used
# as the source control and Jira is used for bug tracking.
# 
# See accompanying README file for help in using this.
# 



from __future__ import with_statement

import logging
import sys
import os

myname = os.path.basename(sys.argv[0])

# Change this value to "CRITICAL/ERROR/WARNING/INFO/DEBUG/NOTSET" 
# as appropriate. 
# loglevel=logging.INFO
# loglevel=logging.DEBUG


import contextlib
import subprocess
import re
import collections
import getpass
import SOAPpy
import traceback
import pprint
import pdb
import stat
import cookielib
import subprocess
import urllib2
import ConfigParser
import string


def main():
    global myname, loglevel
    logging.basicConfig(level=loglevel, format=myname + ":%(levelname)s: %(message)s")

    if myname == "commit-msg" :
        return handle_commit_msg()

    elif myname == "post-commit" :
        return handle_post_commit()

    elif myname == "update":
        return handle_update()

    elif myname == "post-receive":
        return handle_post_receive()


    else:
        logging.error("invoked as '%s'. Need to be invoked as commit-msg, post-commit, update or post-receive" , myname)
        return -1
 

# This function performs the git "commit-msg" hook
# In this function, the commit message text is parsed for the magic
# text referencing Jira issues. 
# It logs into Jira and makes sure that the Jira issues exist
# and are accessible
# This function does not actually add any comments to Jira
# as the user's commit has not yet gone through (that
# Returns: 0 on success, -1 on error
def handle_commit_msg():
    if not enabled_on_branch(git_get_curr_branchname()):
        return 0

    if len(sys.argv) < 2 :
        logging.error("No commit message filename specified") 
        return -1

    commit_msg_filename = sys.argv[1]

    jira_url = get_jira_url()
    if jira_url == None:
        return -1

    try:
        mode = os.stat(commit_msg_filename)[stat.ST_MODE]
        if not stat.S_ISREG(mode):
            logging.error("'%s' is not a valid file", commit_msg_filename)

    except KeyboardInterrupt:
        logging.info('... interrupted')

    except Exception, e:
        logging.error("Failed to open file '%s'", commit_msg_filename)
        logging.debug(e)
        return -1

    (jira_soap_client, jira_auth) = jira_start_session(jira_url)

    if jira_soap_client == None or jira_auth == None:
        return -1

    try:
        commit_msg_text = open(commit_msg_filename).read()

    except KeyboardInterrupt:
        logging.info('... interrupted')

    except Exception, e:
        logging.error("Failed to open file '%s'", commit_msg_filename)
        logging.debug(e)
        return -1

    return validate_commit_text(jira_soap_client, jira_auth, commit_msg_text)


# Performs the git "post-commit" hook
# Uses "git" to find out the most recent commit
# Parses commit message text to find references to Jira issues
# and updates the Jira issue by adding the commit message text
    
# to the issue
# Returns: Nothing (as returning error wont do us any good
#          on a post-commit hook)
def handle_post_commit():
    if not enabled_on_branch(git_get_curr_branchname()):
        return 0

    jira_url = get_jira_url()
    if jira_url == None:
        return

    commit_id = git_get_last_commit_id()
    commit_text = git_get_commit_msg(commit_id) 

    (jira_soap_client, jira_auth) = jira_start_session(jira_url)

    jira_add_comment(jira_soap_client, jira_auth, commit_id, commit_text)
    return 


# Performs the git "update" hook
# This hook is triggered on the remote repo, as a result
# of "git push"
# Parses the old and new commit IDs from argv[2] and argv[3]
# argv[1] contains the "refname"
def handle_update():
    if len(sys.argv) < 4:
        logging.error("update hook called with incorrect no. of parameters")
        return -1

    ref = sys.argv[1] # This is of the form "refs/heads/<branchname>"
    old_commit_id = sys.argv[2]
    new_commit_id = sys.argv[3]

    if not enabled_on_branch(git_get_branchname_from_ref(ref)):
        return 0

    jira_url = get_jira_url()
    if jira_url == None:
        return -1

    (jira_soap_client, jira_auth) = jira_start_session(jira_url)
    if jira_soap_client == None or jira_auth == None:
        return -1

    commit_id_array = git_get_array_of_commit_ids(old_commit_id, new_commit_id)

    for commit_id in commit_id_array:
        commit_text = git_get_commit_msg(commit_id)
        if validate_commit_text(jira_soap_client, jira_auth, commit_text, commit_id) != 0:
            return -1
        
    return 0

# post-receive hook is called with no parameters
# but STDIN has <old-commit-id> <new-commit-id> <refname>
def handle_post_receive():
    buf = sys.stdin.read()
    logging.debug("handle_post_receive: stdin='%s'", buf)
    (old_commit_id, new_commit_id, ref) =  string.split(buf, ' ')


    if old_commit_id == None or new_commit_id == None or ref == None:
        logging.error("post-receive hook stdin is incorrect '%s'", buf)
        return -1

    if not enabled_on_branch(git_get_branchname_from_ref(ref)):
        return 0


    jira_url = get_jira_url()
    if jira_url == None:
        return -1

    (jira_soap_client, jira_auth) = jira_start_session(jira_url)
    if jira_soap_client == None or jira_auth == None:
        return -1

    commit_id_array = git_get_array_of_commit_ids(old_commit_id, new_commit_id)

    if commit_id_array == None or len(commit_id_array)==0:
        logging.error("no commit ids!")
        return -1

    for commit_id in commit_id_array:
        commit_text = git_get_commit_msg(commit_id)
        jira_add_comment(jira_soap_client, jira_auth, commit_id, commit_text)

    return 0
        


def validate_commit_text(jira_soap_client, jira_auth, commit_text, commit_id=None):
    refed_issue_count = call_pattern_hook(commit_text, "refs", \
            jira_find_issue, jira_soap_client, jira_auth, None)

    if refed_issue_count == -1:
        return -1

    fixed_issue_count = call_pattern_hook(commit_text, "fixes", \
            jira_find_issue, jira_soap_client, jira_auth, None)

    if fixed_issue_count == -1:
        return -1


    if refed_issue_count + fixed_issue_count == 0:
        if commit_id != None:
            logging.error("Failed to find any referenced Jira issue\n\tin commit message for commit %s", commit_id)
        else:
            logging.error("Failed to find any referenced Jira issue in commit message(s)")
        return -1

    return 0


def jira_add_comment(jira_soap_client, jira_auth, commit_id, commit_text):
    gitweb_url = get_gitweb_url()
    if gitweb_url != None or gitweb_url != "":
        commit_text_with_url = commit_text.replace(commit_id, \
            "[" + commit_id + "|" + gitweb_url + commit_id + "]")
    else:
        commit_text_with_url = commit_text


    call_pattern_hook(commit_text, 'refs', jira_add_comment_to_issue, \
                                jira_soap_client, jira_auth, commit_text_with_url)
    call_pattern_hook(commit_text, 'fixes', jira_add_comment_to_and_fix_issue, \
                                jira_soap_client, jira_auth, commit_text_with_url)
    return
    

    
    



# Given a function pointer, iterates through the commit message 
# text for Jira magic words, and calls the function repeatedly
# returns number of issues found and touched
# in case of error, return -1
def call_pattern_hook(text, pattern, hookfn, jira_soap_client, jira_auth, jira_text):
    if not callable(hookfn):
        logging.error("Hook function is not callable");
        exit -1

    magic = re.compile(pattern + ' #\w\w*-\d\d*')
    
    iterator = magic.finditer(text)
    issue_count = 0
    for match in iterator: 
        issuekey = match.group().split(" ", 2)[1].strip('#')
        # print "issuekey found=", issuekey
        ret = hookfn(issuekey, jira_soap_client, jira_auth, jira_text)
        if ret != 0:
            return -1
        else:
            issue_count += 1

    return issue_count

#-----------------------------------------------------------------------------
# Jira helper functions
#


# Given a Jira server URL (which is stored in git config)
# Starts an authenticated jira session using SOAP api
# Returns a list of the SOAP object and the authentication token
def jira_start_session(jira_url):
    jira_url = jira_url.rstrip("/")
    try:
        handle = urllib2.urlopen(jira_url + "/rpc/soap/jirasoapservice-v2?wsdl")
        soap_client = SOAPpy.WSDL.Proxy(handle)
        # print "self.soap_client set", self.soap_client

    except KeyboardInterrupt:
        logging.info("... interrupted")

    except Exception, e:
        save_jira_cached_auth(jira_url, "")
        logging.error("Invalid Jira URL: '%s'", jira_url)
        logging.debug(e)
        return -1

    auth = jira_login(jira_url, soap_client)
    if auth == None:
        return (None, None)

    return (soap_client, auth)

# Try to use the cached authentication object to log in
# to Jira first. ("implicit")
# if that fails, then prompt the user ("explicit")
# for username/password
def jira_login(jira_url, soap_client):

    auth = get_jira_cached_auth(jira_url)
    if auth != None and auth != "": 
        auth = jira_implicit_login(soap_client, auth) 
    else:
        auth = None

    if auth == None:
        save_jira_cached_auth(jira_url, "")
        auth = jira_explicit_login(soap_client)


    if auth != None:
        save_jira_cached_auth(jira_url, auth)

    return auth

def jira_implicit_login(soap_client, auth):

    # test jira to see if auth is valid
    try:
        jira_types = soap_client.getIssueTypes(auth)
        return auth
    except KeyboardInterrupt:
        logging.info("... interrupted")

    except Exception, e:
        print >> sys.stderr, "Previous Jira login is invalid or has expired"
        # logging.debug(e)
        

    return None

def jira_explicit_login(soap_client):
    max_retry_count = 3
    retry_count = 0

    while retry_count < max_retry_count:
        if retry_count > 0:
            logging.info("Invalid Jira password/username combination, try again")

        # We now need to read the Jira username/password from
        # the console.
        # However, there is a problem. When git hooks are invoked
        # stdin is pointed to /dev/null, see here:
        # http://kerneltrap.org/index.php?q=mailarchive/git/2008/3/4/1062624/thread
        # The work-around is to re-assign stdin back to /dev/tty , as per
        # http://mail.python.org/pipermail/patches/2002-February/007193.html
        sys.stdin = open('/dev/tty', 'r')

        username = raw_input('Jira username: ')
        password = getpass.getpass('Jira password: ')

        # print "abc"
        # print "self.soap_client login...%s " % username + password
        try:
            auth = soap_client.login(username, password) 

            try:
                jira_types = soap_client.getIssueTypes(auth)
                return auth

            except KeyboardInterrupt:
                logging.info("... interrupted")

            except Exception,e:
                logging.error("User '%s' does not have access to Jira issues")
                return None

        except KeyboardInterrupt:
            logging.info("... interrupted")

        except Exception,e:
            logging.debug("Login failed")

        auth=None
        retry_count = retry_count + 1


    if auth == None:
        logging.error("Invalid Jira password/username combination")

    return auth



def jira_find_issue(issuekey, jira_soap_client, jira_auth, jira_text):
    try:
        issue = jira_soap_client.getIssue(jira_auth, issuekey)
        logging.debug("Found issue '%s' in Jira: (%s)",  
                    issuekey, issue["summary"])
        return 0

    except KeyboardInterrupt:
        logging.info("... interrupted")

    except Exception, e:
        logging.error("No such issue '%s' in Jira", issuekey)
        logging.debug(e)
        return -1


def jira_add_comment_to_issue(issuekey, jira_soap_client, jira_auth, jira_text):
    try:
        jira_soap_client.addComment(jira_auth, issuekey, {"body":jira_text})
        logging.debug("Added to issue '%s' in Jira:\n%s", issuekey, jira_text)

    except Exception, e:
        logging.error("Error adding comment to issue '%s' in Jira", issuekey)
        logging.debug(e)
        return -1


# TODO: Not fully implemented yet!
def jira_add_comment_to_and_fix_issue(issuekey, jira_soap_client, jira_text):
    return jira_add_comment_to_issue(issuekey, jira_soap_client, jira_text)




#-----------------------------------------------------------------------------
# Miscellaneous Jira related utility functions
#
def get_jira_url():
    jira_url = git_config_get("jira.url")
    if jira_url == None or jira_url == "":
        logging.error("Jira URL is not set. Please use 'git config jira.url <actual-jira-url> to set it'")
        return None

    return jira_url

def get_jira_cached_auth(jira_url):
    return get_cfg_value(os.environ['HOME'] + "/.jirarc", jira_url, "auth")

def save_jira_cached_auth(jira_url, auth):
    return save_cfg_value(os.environ['HOME'] + "/.jirarc", jira_url, "auth", auth)


#---------------------------------------------------------------------
# Misc. helper functions
#
def get_gitweb_url():
    return git_config_get("gitweb.url")

def get_cfg_value(cfg_file_name, section, key):
    try:
        cfg = ConfigParser.ConfigParser()
        cfg.read(cfg_file_name)
        value = cfg.get(section, key)
    except:
        return None
    return value
    

def save_cfg_value(cfg_file_name, section, key, value):
    try:
        cfg = ConfigParser.SafeConfigParser()
    except Exception, e:
        logging.warning("Failed to instantiate a ConfigParser object")
        logging.debug(e)
        return

    try:
        cfg.read(cfg_file_name)
    except Exception, e:
        logging.warning("Failed to read .jirarc")
        logging.debug(e)
        return

    try:
        cfg.add_section(section)
    except ConfigParser.DuplicateSectionError,e:
        logging.debug("Section '%s' already exists in '%s'", section, cfg_file_name)

    try:
        cfg.set(section, key, value)
    except Exception,e:
        logging.warning("Failed to add '%s' to '%s'", key, cfg_file_name)
        logging.debug(e)

    try:
        cfg.write(open(cfg_file_name, 'wb'))
    except Exception, e:
        logging.warning("Failed to write '%s'='%s' to file %s", key, value, cfg_file_name)
        logging.debug(e)
        return

# given a string, executes it as an executable, and returns the STDOUT
# as a string
def get_shell_cmd_output(cmd):
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
        return proc.stdout.read().rstrip('\n')
    except KeyboardInterrupt:
        logging.info("... interrupted")

    except Exception, e:
        logging.error("Failed trying to execute '%s'", cmd)

#----------------------------------------------------------------------------
# git helper functions
#

# Read git config of "git-jira-hook.branches"
# Parse out the comma (and space) separated list of
# branch names.
# Then compare against current branchname to see
# if we need to be enabled.
# Return False if we should not be enabled
def enabled_on_branch(current_branchname):
    logging.debug("Test if '%s' is enabled...", current_branchname)
    branchstr = git_config_get("git-jira-hook.branches")
    if branchstr == None or string.strip(branchstr) == "":
        logging.debug("All branches enabled")
        return not False

    branchlist = string.split(branchstr, ',')

    for branch in branchlist:
        branch = string.strip(branch)
        if current_branchname == branch:
            logging.debug("Current branch '%s' is enabled", current_branchname)
            return not False

    logging.debug("Curent branch '%s' is NOT enabled", current_branchname)
    return False

# Get our current branchname
def git_get_curr_branchname():
    buf = get_shell_cmd_output("git branch --no-color")
    # buf is a multiline output, each line containing a branch name
    # the line that starts with a "*" contains the current branch name

    m = re.search("^\* .*$", buf, re.MULTILINE)
    if m == None:
        return None

    return buf[m.start()+2 : m.end()]


# Given a "ref" string (such as while doing a push
# to a remote repo), parse out the branch name
def git_get_branchname_from_ref(ref):
    # "refs/heads/<branchname>"
    if string.find(ref, "refs/heads") != 0:
        logging.error("Invalid ref '%s'", ref)
        exit -1

    return string.strip(ref[len("refs/heads/"):])


def git_config_get(name):
    return get_shell_cmd_output("git config '" + name + "'")

def git_config_set(name, value):
    os.system("git config " + name + " '" + value + "'")

def git_config_unset(name):
    os.system("git config --unset-all " + name)

def git_get_commit_msg(commit_id):
    return get_shell_cmd_output("git rev-list --pretty --max-count=1 " + commit_id)

def git_get_last_commit_id():
    return get_shell_cmd_output("git log --pretty=format:%H -1")

def git_get_array_of_commit_ids(start_id, end_id):
    output = get_shell_cmd_output("git rev-list " + start_id + ".." + end_id)
    if output == "":
        return None
    
    # parse the result into an array of strings
    commit_id_array = string.split(output, '\n')
    return commit_id_array

    
#----------------------------------------------------------------------------
# python script entry point. Dispatches main()
if __name__ == "__main__":
  exit (main())