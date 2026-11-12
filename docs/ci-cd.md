# Stratégie CI/CD retenue

La chaîne CI doit être simple, rapide et reproductible : lint, tests unitaires, build Docker, puis publication de l’image sur le registre GitHub Container Registry. La branche `main` est la seule branche de publication ; les branches de travail ne doivent pas pousser de version exploitable. L’image porte un tag horodaté associé au SHA du commit pour suivre précisément la source du binaire livré. L’objectif est de limiter les erreurs humaines tout en gardant une infrastructure facilement compréhensible et traçable pour l’équipe.
