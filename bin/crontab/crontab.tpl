#
# {{ header }}
#

MAILTO=input-tracebacks@mozilla.com

HOME=/tmp

# Once a day at 2:00am do an svn up and run the l10n completion script
0,10,20,30,40,50 * * * * {{ user }} cd {{ webapp }} && ./bin/run_l10n_completion.sh {{ webapp }} {{ python }}
