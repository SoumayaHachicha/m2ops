# La Gazette — M2Ops

La Gazette collecte les flux RSS/Atom configurés, valide les articles des
24 dernières heures, évite les doublons, les regroupe par thèmes et produit
un bulletin JSON. Le système ne télécharge pas les pages des articles.

## Exécution planifiée avec Docker

```bash
docker compose build
docker compose up -d
docker compose logs -f app
```

Le service planifie une collecte tous les jours à 6 h 30 (heure
`Europe/Paris`), pour laisser une marge avant la livraison prévue à 7 h.
Le conteneur doit rester démarré pour respecter cet horaire. Pour lancer une
collecte immédiatement, utilisez `python -m src.pipeline`.

Les résultats sont écrits dans :

- `reports/edition.json` : bulletin courant, groupé par thème ;
- `reports/quality.json` : volumes collectés, doublons, rejets et erreurs ;
- `reports/alerts.jsonl` : alertes de collecte et édition vide ;
- `articles_bruts/` : articles conservés sous forme de champs RSS minimaux ;
- `data/m2ops.sqlite3` : état des sources et exécutions.

Les journaux JSON sont accessibles avec `docker compose logs app`.

## Exécution ponctuelle en local

Avec Python 3.12 :

```bash
python -m src.pipeline
```

Options disponibles :

```bash
python -m src.pipeline --help
```

Le parseur RSS/Atom autonome reste disponible pour exporter un seul flux :

```bash
python -m src --source "Le Monde" --url "https://www.lemonde.fr/rss/une.xml" --output "./tmp/edition.json"
```

## Sources et conformité

Les flux sont configurés dans `sources.csv`. Avant toute utilisation réelle,
vérifiez auprès de chaque éditeur que l’accès, la conservation des extraits et
la redistribution du bulletin sont autorisés. La présence d’une URL publique
ne constitue pas une autorisation juridique.

## Développement et tests

```bash
python -m pytest -q
python -m flake8 src tests
```

Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour les règles de contribution.
