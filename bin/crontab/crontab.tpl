#
# {{ header }}
#

MAILTO=input-tracebacks@mozilla.com

HOME=/tmp

# Once a day at 2:00am do an svn up and run the l10n completion script
0 2 * * * cd {{ webapp }}/locale && svn up && cd {{ webapp }} && {{ python }} ./bin/l10n_completion.py --truncate 90 ./media/l10n_completion.json ./locale/
