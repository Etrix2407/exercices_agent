@echo off
rem Déclenchement nocturne de lancer_session.py, appelé par le planificateur de tâches.
rem MODE vaut --simulation tant que l'essai réel n'a pas été validé ; remplacer par --reel ensuite.
rem En mode réel, la clé est lue dans la variable d'environnement utilisateur ANTHROPIC_API_KEY
rem (setx ANTHROPIC_API_KEY ...) ou dans le profil créé par « ant auth login ».

set MODE=--simulation
set KIT=%~dp0..
set PYTHON=%KIT%\..\.venv\Scripts\python.exe

cd /d "%KIT%"
if not exist sorties mkdir sorties
"%PYTHON%" lancer_session.py %MODE% --duree-max 1800 --tokens-max 3000000 --budget-centimes 500 >> sorties\nuit.log 2>&1
exit /b %ERRORLEVEL%
