# Feux de forêt — Intégration Home Assistant

Intégration non officielle pour suivre les feux de forêt en France à partir des données publiques de [feuxdeforet.fr](https://feuxdeforet.fr).

## Version

- Version actuelle : 1.0.0
- Première version déposée : 1.0.0

## Changelog

### 1.0.0 - 2026-07-11
- Première publication de l’intégration.
- Détection des feux confirmés et des signalements en attente.
- Alertes locales, notifications persistantes/Telegram et tableau de bord Lovelace d’exemple.

## Fonctionnalités

- Une entité de géolocalisation par feu détecté, confirmé ou en attente de confirmation.
- Un capteur binaire d’alerte quand un feu entre dans le rayon configuré.
- Cinq capteurs d’information : proximité, feux confirmés, signalements en attente, distance du plus proche, dernière actualisation.
- Notifications persistantes Home Assistant et/ou Telegram.
- Détection anticipée pour les signalements très récents, avant publication officielle.

## Installation

### Via HACS
1. Ouvrir HACS → Custom repositories.
2. Ajouter l’URL du dépôt.
3. Sélectionner la catégorie Integration et installer Feux de forêt.
4. Redémarrer Home Assistant.

### Manuelle
1. Copier le dossier custom_components/feux_de_foret dans votre configuration Home Assistant.
2. Redémarrer Home Assistant.

## Configuration

1. Ouvrir Paramètres → Appareils et services → Ajouter une intégration.
2. Sélectionner Feux de forêt.
3. Définir le nom de la zone, la latitude, la longitude, le rayon d’alerte et l’intervalle de rafraîchissement.

## Entités créées

Avec le nom de zone par défaut “Feux de forêt”, l’intégration crée par exemple :

- sensor.feux_de_foret_feux_en_cours_a_proximite
- sensor.feux_de_foret_feux_confirmes
- sensor.feux_de_foret_signalements_en_attente
- sensor.feux_de_foret_distance_du_feu_le_plus_proche
- sensor.feux_de_foret_derniere_actualisation_des_donnees (désactivé par défaut)
- binary_sensor.feux_de_foret_alerte_feu_de_foret_a_proximite
- geo_location.feux_de_foret_<commune>_<departement> (une par feu)

Si vous avez renommé la zone, le préfixe des entity_id change, mais les noms d’entités restent les mêmes.

## Options utiles

- Rayon d’alerte : sert à l’alerte locale, au comptage des feux à proximité et au seuil des notifications.
- Intervalle de rafraîchissement : de 1 à 60 minutes, avec curseur et saisie directe.
- Notifications Telegram : si un service notify est déjà configuré.

## Lovelace

Le fichier [lovelace_feux_de_foret.yaml](lovelace_feux_de_foret.yaml) propose un exemple de tableau de bord prêt à l’emploi avec :

- une carte nationale des feux,
- un résumé rapide des compteurs et de l’alerte,
- des cartes Markdown conditionnelles pour les feux autour de vous, tous les feux par distance et tous les feux par date,
- des liens vers les fiches détaillées quand elles sont disponibles.

Si vous avez changé le nom de la zone, remplacez simplement le préfixe des entity_id dans le YAML. Si aucune date officielle n’est fournie par feuxdeforet.fr, l’intégration utilise une date de détection interne comme valeur de secours.

## Avertissement

Ce projet n’est pas affilié à feuxdeforet.fr. Les données sont fournies “en l’état” et ne doivent pas remplacer les consignes officielles en cas de danger.

## Licence

MIT — voir [LICENSE](LICENSE).
