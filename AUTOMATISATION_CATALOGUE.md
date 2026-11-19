# Veille et publication automatiques de CREATARIA

## Ce que fait le robot

- Interroge quotidiennement des flux RSS Google News en français, anglais,
  espagnol, japonais et portugais, avec des requêtes générales sur les loisirs
  créatifs et l'artisanat.
- Classe les résultats dans les 24 familles de `catalogue_grid.json` à partir
  d'un vocabulaire multilingue couvrant les techniques et matériaux de chaque
  famille. Les crèches, sapins, cœurs ou personnages ne forment pas une liste
  limitative.
- Ne télécharge pas les articles, tutoriels ni photos. Il conserve le titre,
  le lien, l'éditeur et la date comme attribution de la piste trouvée.
- Produit une variante originale à partir d'une fiche complète CREATARIA de la
  même famille. Les matériaux, étapes et patrons viennent de cette fiche de
  référence; le thème trouvé en ligne ne sert qu'à proposer une variation
  décorative. Le robot n'invente pas une méthode technique à partir d'un titre
  d'article.
- Écarte les doublons et les résultats sans famille identifiable. Ajoute au
  plus 24 fiches par exécution, deux par famille, puis recalcule
  `catalogue_grid_status.json` et l'empreinte de `manifest.json`.
- Le workflow GitHub Actions s'exécute chaque jour, enregistre les nouveaux
  fichiers avec son `GITHUB_TOKEN`, puis publie directement GitHub Pages.

## Mise en service sur GitHub

Les fichiers `catalog_robot.py`, `catalogue_grid_builder.py`,
`catalogue_grid.json`, `creations.json`, `manifest.json` et
`catalog_update.json` doivent se trouver à la racine du dépôt qui sert
`https://aria9128.github.io/creataria-catalogue/`. Le workflow doit se trouver
dans `.github/workflows/catalog_robot.yml` à cette même racine.

Le workflow utilise le jeton temporaire intégré à GitHub Actions; aucun jeton
personnel ni clé d'API n'est enregistré dans le code. Il demande les accès
minimaux requis pour écrire le contenu du dépôt et déployer Pages. Le dépôt doit
autoriser GitHub Actions et GitHub Pages doit accepter les déploiements Actions
(ou être configuré sur la branche d'où part le workflow). Si les paramètres du
dépôt interdisent les écritures Actions, GitHub bloquera le commit automatique.

## Limite de couverture

Internet n'a pas d'index exhaustif et les flux RSS ne représentent pas chaque
site, chaque langue ni chaque création publiée. Cette veille recherche un
large éventail de techniques et de matériaux dans cinq espaces linguistiques;
elle ne peut honnêtement garantir « toutes les créations d'Internet ». Les
nouveaux matériaux non reconnus sont ignorés plutôt que transformés en fiche
hasardeuse. Le vocabulaire de classement peut être élargi dans
`FAMILY_KEYWORDS` sans modifier la grille fixe de 216 cellules.
