# Feux de forêt — Intégration Home Assistant

Intégration non officielle pour suivre les feux de forêt en France à partir des données publiques de [feuxdeforet.fr](https://feuxdeforet.fr).

## Version

- Version actuelle : 1.3.0
- Première version déposée : 1.0.0

## Changelog

### 1.3.0 - 2026-08-19
- Ajout de la gestion des feux éteints : icône dédiée, attribut `eteint` et affichage distinct dans l'exemple Lovelace.
- Ajout des attributs `etat_change_le` et `etat_change_depuis`, alimentés en priorité par la date de mise à jour fournie par feuxdeforet.fr, avec repli local si nécessaire.
- Ajout de l'événement `feux_de_foret_fire_status_changed`, émis uniquement lorsqu'un feu change réellement de statut ou d'état, pour déclencher des automatisations ciblées.
- Ajout de l'option `status_flap_grace_minutes` (défaut 45 min) : un feu temporairement absent du flux confirmé/en attente est conservé avant suppression, afin d'éviter les recréations et notifications en double.
- Amélioration de la récupération des détails des feux sortis du flux pendant la période de grâce.
- Les entités `geo_location` sont affichées comme données principales et ne sont plus classées en diagnostic.
- Le nettoyage des feux supprimés purge également les dates de détection et les identifiants de notifications mémorisés.
- Les réglages de rayon, intervalle de rafraîchissement et délais de grâce utilisent des curseurs dans le flux de configuration.
- Mise à jour de l'exemple Lovelace : état éteint et ancienneté du dernier changement visibles dans les listes.

### 1.2.0 - 2026-08-04
- Le nettoyage des entités geo_location compare désormais l'entity registry
  au flux actuel, au lieu de se fier au seul état en mémoire du manager
  (réinitialisé à chaque redémarrage). Les feux disparus du flux pendant
  que l'intégration était hors ligne sont maintenant bien supprimés.
- Ajout de l'option 'unavailable_grace_minutes' (défaut 15 min) : un échec
  de récupération feuxdeforet.fr transitoire ne fait plus basculer
  immédiatement toutes les entités (binary_sensor + sensors) en
  indisponible ; les dernières données connues sont conservées le temps
  du délai de grâce.
- Les entités geo_location ne sont plus catégorisées en diagnostic et
  redeviennent visibles dans les tableaux de bord auto-générés.
- Le nettoyage des feux orphelins purge aussi `fire_detection_dates` et
  `notified_fire_ids`.
- Mise à jour de l'exemple Lovelace.

### 1.1.1 - 2026-07-24
- Mise à jour du README (changelog, documentation).
- Correction du workflow de publication GitHub (permissions insuffisantes empêchant l'upload de l'asset de release).
- Mise en conformité du code avec les règles de lint ruff (imports triés, gestion des exceptions explicitée).

### 1.1.0 - 2026-07-23
- Correction de performance majeure : les appels réseau de résolution (commune, date, détails) sont désormais exécutés en parallèle par lots limités, au lieu d'un traitement séquentiel qui pouvait bloquer le démarrage de Home Assistant plusieurs dizaines de secondes.
- Le peuplement des entités geo_location ne bloque plus le démarrage de l'intégration (traitement en tâche de fond).
- Ajout d'un repli par géocodage inverse quand la résolution officielle échoue ou qu'aucune URL n'est fournie par l'API, ce qui évite l'apparition d'entités "Zone inconnue".
- Mise en cache définitive des échecs 404 permanents pour éviter de retenter indéfiniment des feux disparus de la source, tout en continuant de réessayer les erreurs transitoires (500/502/503).
- Nettoyage fin des entités obsolètes (feux disparus du flux) sans purge globale au démarrage.

### 1.0.1 - 2026-07-11
- Corrections mineures.

### 1.0.0 - 2026-07-11
- Première publication de l'intégration.
- Détection des feux confirmés et des signalements en attente.
- Alertes locales, notifications persistantes/Telegram et tableau de bord Lovelace d'exemple.

## Fonctionnalités

- Une entité de géolocalisation par feu détecté, confirmé ou en attente de confirmation.
- Un capteur binaire d'alerte quand un feu entre dans le rayon configuré.
- Cinq capteurs d'information : proximité, feux confirmés, signalements en attente, distance du plus proche, dernière actualisation.
- Notifications persistantes Home Assistant et/ou Telegram.
- Détection anticipée pour les signalements très récents, avant publication officielle.

## Installation

### Via HACS
1. Ouvrir HACS → Custom repositories.
2. Ajouter l'URL du dépôt.
3. Sélectionner la catégorie Integration et installer Feux de forêt.
4. Redémarrer Home Assistant.

### Manuelle
1. Copier le dossier custom_components/feux_de_foret dans votre configuration Home Assistant.
2. Redémarrer Home Assistant.

## Configuration

1. Ouvrir Paramètres → Appareils et services → Ajouter une intégration.
2. Sélectionner Feux de forêt.
3. Définir le nom de la zone, la latitude, la longitude, le rayon d'alerte et les options souhaitées.

## Entités créées

Avec le nom de zone par défaut "Feux de forêt", l'intégration crée par exemple :

- sensor.feux_de_foret_feux_en_cours_a_proximite
- sensor.feux_de_foret_feux_confirmes
- sensor.feux_de_foret_signalements_en_attente
- sensor.feux_de_foret_distance_du_feu_le_plus_proche
- sensor.feux_de_foret_derniere_actualisation_des_donnees (désactivé par défaut)
- binary_sensor.feux_de_foret_alerte_feu_de_foret_a_proximite
- geo_location.feux_de_foret_<commune>_<departement> (une par feu)

Si vous avez renommé la zone, le préfixe des entity_id change, mais les noms d'entités restent les mêmes.

## Options utiles

- **Rayon d'alerte** : de 1 à 500 km; sert à l'alerte locale et au comptage des feux à proximité.
- **Intervalle de rafraîchissement** : de 1 à 60 minutes.
- **Délai de grâce avant indisponibilité** : de 0 à 120 minutes (défaut 15); conserve les dernières données si le site est momentanément inaccessible. `0` rétablit l'indisponibilité immédiate.
- **Délai de grâce avant suppression** : de 0 à 180 minutes (défaut 45); conserve une entité lorsqu'un feu sort temporairement du flux confirmé/en attente. `0` rétablit la suppression immédiate.
- **Notifications persistantes** : crée une notification Home Assistant pour chaque nouveau feu ou signalement.
- **Distance maximale de notification** : de 0 à 500 km; `0` utilise le rayon d'alerte.
- **Notifications Telegram** : nécessite un service `notify` Telegram déjà configuré dans Home Assistant.
- **Journalisation détaillée** : active les logs de diagnostic de l'intégration.

Les réglages du rayon, de l'intervalle et des deux délais de grâce sont proposés sous forme de curseurs dans le formulaire Home Assistant.

### Automatisations sur changement d'état

L'événement `feux_de_foret_fire_status_changed` est émis lorsqu'un feu change réellement d'état ou de statut. Il peut être utilisé comme déclencheur d'automatisation :

```yaml
trigger:
  - platform: event
    event_type: feux_de_foret_fire_status_changed
action:
  - service: notify.mobile_app_telephone
    data:
      message: >-
        {{ trigger.event.data.commune_departement }} :
        {{ trigger.event.data.etat_label }}
```

Les données de l'événement comprennent notamment `fire_id`, `entity_id`, `commune_departement`, `etat`, `etat_precedent`, `confirme`, `eteint`, `distance_km` et `url`.

## Lovelace

Le fichier [lovelace_feux_de_foret.yaml](lovelace_feux_de_foret.yaml) propose un exemple de tableau de bord prêt à l'emploi avec :

- une carte nationale des feux,
- un résumé rapide des compteurs et de l'alerte,
- des cartes Markdown conditionnelles pour les feux autour de vous, tous les feux par distance et tous les feux par date,
- des liens vers les fiches détaillées quand elles sont disponibles.

Si vous avez changé le nom de la zone, remplacez simplement le préfixe des entity_id dans le YAML. Si aucune date officielle n'est fournie par feuxdeforet.fr, l'intégration utilise une date de détection interne comme valeur de secours.

## Avertissement

Ce projet n'est pas affilié à feuxdeforet.fr. Les données sont fournies "en l'état" et ne doivent pas remplacer les consignes officielles en cas de danger.

## Licence

MIT — voir [LICENSE](LICENSE).