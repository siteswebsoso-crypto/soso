# Site vitrine full SEO pour une entreprise locale

> Recette d'exemple : modifiez-la librement (`~/.jarvis/playbooks/site-vitrine-seo.md`)
> ou dictez vos ajouts à Jarvis (« Jarvis, ajoute à la recette site SEO : … »).

## Recherche préalable
- Rechercher l'entreprise sur le web : activité, adresse, horaires, téléphone, avis, réseaux sociaux.
- Identifier 3 concurrents locaux et les mots-clés sur lesquels ils se positionnent.
- Établir la liste de mots-clés : 1 principal par page, format « service + ville » (ex : « plombier Lyon 3 »),
  plus les requêtes longues (« dépannage plomberie urgence Lyon dimanche »).

## Stack technique
- Site statique, ultra rapide : Astro (ou HTML/CSS pur si très petit), sans framework JS lourd.
- Responsive mobile-first, accessible (contrastes AA, attributs alt, navigation clavier).
- Objectif Lighthouse ≥ 95 sur les 4 scores. Images en WebP/AVIF, dimensions explicites, lazy-loading.

## Arborescence
- Accueil, une page par service principal, À propos, Avis/Réalisations, Contact, Mentions légales,
  Politique de confidentialité. Un blog avec 3 premiers articles optimisés si pertinent.
- URLs courtes en minuscules avec tirets, contenant le mot-clé.

## SEO on-page (chaque page)
- Un seul `<h1>` avec le mot-clé principal ; hiérarchie h2/h3 logique.
- `<title>` ≤ 60 caractères et meta description ≤ 155 caractères, uniques et incitatives.
- Au moins 600 mots de contenu original et utile sur les pages services (pas de remplissage).
- Maillage interne entre services, liens vers la page contact, fil d'Ariane.
- Balises Open Graph et Twitter Card, URL canonique, `lang="fr"`.

## SEO technique
- Données structurées JSON-LD : `LocalBusiness` (adresse, horaires, géo, téléphone), `BreadcrumbList`,
  `FAQPage` si une FAQ existe, `Review`/`AggregateRating` uniquement avec de vrais avis.
- `sitemap.xml`, `robots.txt`, page 404 personnalisée, favicon et manifest.
- Coordonnées NAP (nom, adresse, téléphone) identiques partout, Google Maps intégré sur Contact.

## Conversion
- Bouton d'appel cliquable (`tel:`) visible en permanence sur mobile.
- Formulaire de contact simple (prévoir Formspree ou équivalent, sans backend).
- Appels à l'action clairs sur chaque page.

## Livraison
- README avec : lancer en local, construire, déployer (Netlify / Vercel / OVH).
- Fichier `SEO-CHECKLIST.md` listant ce qui a été fait et ce qui reste à faire par le client
  (fiche Google Business Profile, Search Console, collecte d'avis).
- Ne PAS mettre en ligne ni acheter de nom de domaine sans validation de l'utilisateur.
