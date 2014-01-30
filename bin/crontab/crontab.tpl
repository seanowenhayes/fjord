#
# {{ header }}
#

MAILTO=input-tracebacks@mozilla.com

HOME=/tmp

# Once a day at 2:00am do an svn up and run the l10n completion script
# Note: This runs as root so it has access to the locale/ directory
# to do an svn up.
0,10,20,30,40,50 * * * * root cd {{ source }} && ./bin/run_l10n_completion.sh {{ source }} {{ python }}
