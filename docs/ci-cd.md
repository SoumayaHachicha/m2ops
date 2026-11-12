# Vérifications automatisées

À chaque push sur `main` et pour chaque pull request, GitHub Actions exécute Flake8, les tests unitaires et un build Docker. La publication sur un registre d’images n’est pas automatisée : elle nécessiterait de configurer et valider séparément les droits du registre.
