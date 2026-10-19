# Crée, consulte ou supprime la tâche planifiée Windows qui lance lancer_nuit.cmd chaque nuit à 2 h.
# Tâche au nom de l'utilisateur courant : aucun droit d'administrateur requis.
# La tâche ne s'exécute que si la session Windows est ouverte (comportement par défaut sans mot de passe).
#
# Usage, depuis ce dossier :
#   powershell -ExecutionPolicy Bypass -File planifier_windows.ps1            # créer
#   powershell -ExecutionPolicy Bypass -File planifier_windows.ps1 -Voir      # consulter
#   powershell -ExecutionPolicy Bypass -File planifier_windows.ps1 -Supprimer # supprimer

param([switch]$Voir, [switch]$Supprimer)

$Nom = "TriNocturneConsultations"
$Script = Join-Path $PSScriptRoot "lancer_nuit.cmd"

if ($Supprimer) {
    schtasks /Delete /TN $Nom /F
} elseif ($Voir) {
    schtasks /Query /TN $Nom /V /FO LIST
} else {
    # /SC DAILY /ST 02:00 : tous les jours à 2 h ; /F : remplace une tâche du même nom.
    schtasks /Create /TN $Nom /TR "`"$Script`"" /SC DAILY /ST 02:00 /F
    Write-Output "Tâche $Nom créée. Lancement immédiat pour essai : schtasks /Run /TN $Nom"
}
