# Contributing

## Stratégie de branches

- `main` est la branche de production et doit toujours être déployable.
- Créer une branche dédiée par sujet ou par correctif : `feature/nom`, `fix/nom`, `docs/nom`.
- Le code ne doit être mergé sur `main` qu’après validation de la CI et revue rapide.

## Convention de commits

Utilisez des messages courts et explicites :

```text
feat: ajouter le parseur RSS
fix: corriger la date de publication
docs: détailler la stratégie CI/CD
```

## Règles de revue

- Une PR doit être courte et lisible.
- Les tests doivent passer avant le merge.
- Les changements impactant l’infrastructure doivent être validés en local avec Docker Compose.

## Outils de validation

```bash
./bin/test

docker compose build
```
