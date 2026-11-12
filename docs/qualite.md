# Règles de qualité et de rejet

Les contrôles sont appliqués par le collecteur. Le rapport agrégé est écrit
dans `reports/quality.json` ; le contenu des articles rejetés n’est pas
conservé.

## Règles de validation

| Règle | Description |
| --- | --- |
| `R00_titre_vide` | Rejette un titre absent ou vide après normalisation. |
| `R01_publi` | Rejette les contenus sponsorisés et publi-reportages détectés par mots-clés. |
| `R02_horoscope` | Rejette les contenus d’horoscope détectés par mots-clés. |
| `R03_programme_tv` | Rejette les programmes TV détectés par mots-clés. |
| `R04_jeu` | Rejette les jeux et concours détectés par mots-clés. |
| `R05_date_future` | Rejette les dates postérieures à l’heure de collecte. |
| `R06_lien_vide` | Rejette un article sans lien. |
| `R07_date_invalide` | Rejette une date absente, invalide ou sans fuseau reconnu. |
| `R08_article_perime` | Rejette un article publié il y a plus de 24 heures. |
| `R09_lien_invalide` | Rejette un lien qui n’est pas une URL HTTP ou HTTPS. |

Les règles éditoriales par mots-clés sont des heuristiques : elles peuvent
produire des faux positifs ou manquer certains cas. Les doublons sont
comptabilisés séparément selon le lien canonique ou la similarité du titre.

## Rapport qualité

Le rapport donne les articles ajoutés, doublons écartés, rejets par règle et
par source, articles retenus pour l’édition et échecs de collecte. Les
événements nécessitant une intervention sont également consignés dans
`reports/alerts.jsonl` et dans les logs JSON du conteneur. Un flux sans
élément et une édition sans article génèrent aussi une alerte.
