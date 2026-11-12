# Données et conservation

## Données d’un article

Les fichiers de `articles_bruts/` et le bulletin contiennent uniquement les
champs éditoriaux nécessaires :

- `source` : nom de la source ;
- `title` : titre ;
- `description` : extrait normalisé, limité à 220 caractères ;
- `link` : lien vers l’article original ;
- `published_at` : date de publication normalisée en UTC.

La base SQLite ajoute un identifiant technique et la date de collecte. Le
champ `payload` de la table `articles` est une copie JSON des cinq champs
ci-dessus ; le XML complet du flux, les pages d’articles, les commentaires,
les profils et les identifiants de lecteurs ne sont pas conservés.

## Tables principales

`sources` contient le nom, le type, l’URL du flux, l’état de collecte, les
échecs consécutifs et les en-têtes HTTP conditionnels.

`articles` contient les champs éditoriaux, la date de collecte et un
identifiant interne. Une contrainte d’unicité empêche de réinsérer un même
lien pour une même source.

`runs`, `themes` et `articles_themes` conservent les résultats et métriques
du regroupement thématique.

## Fraîcheur et déduplication

Seuls les articles dont la date de publication est valide et comprise dans
les dernières 24 heures sont conservés. Les enregistrements expirés ou ayant
une date invalide sont purgés au démarrage d’une collecte.

Les doublons sont écartés à partir du lien canonique, du titre normalisé ou
d’une forte similarité entre titres. Ces règles restent heuristiques et
doivent être surveillées dans `reports/quality.json`.

Les motifs de rejet sont agrégés dans le rapport qualité ; le contenu rejeté
n’est pas conservé.

## Protection des données et droits

Le système ne collecte pas de comptes, de commentaires ou de profils de
lecteurs. Un extrait RSS peut néanmoins mentionner une personne : la
conformité de son traitement, la durée de conservation et les conditions
d’utilisation de chaque éditeur doivent être vérifiées par l’équipe avant
tout usage réel. Une URL publique ne vaut pas autorisation de republication.
