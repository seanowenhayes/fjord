#
# {{ header }}
#

MAILTO=input-tracebacks@mozilla.com

HOME=/tmp

# Once a day at 2:00am do an svn up and run the l10n completion script
0 2 * * * cd {{ webapp }} && ./bin/run_l10n_completion.sh {{ python }}
