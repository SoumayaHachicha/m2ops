# Regroupement des thèmes

Le pipeline attribue chaque article récent à un thème à partir de mots-clés
présents dans son titre et son extrait : politique, économie, sport, culture,
société, sciences ou autres. Les règles sont déterministes et n’utilisent
pas de modèle génératif ni de modèle entraîné.

Cette classification est une heuristique de démonstration ; elle doit être
évaluée sur les articles réels avant d’être considérée comme éditorialement
fiable. Les articles sans mot-clé reconnu sont placés dans « Autres » plutôt
que perdus.

Chaque exécution est enregistrée dans `runs` avec sa fenêtre temporelle, ses
paramètres, ses métriques et ses thèmes. Les tables `themes` et
`articles_themes` enregistrent le regroupement correspondant.
