# Contribuer à Feux de forêt

Merci de votre intérêt pour contribuer à cette intégration Home Assistant !

## Signaler un bug

Utilisez le modèle "Signaler un bug" lors de la création d'une issue, et joignez
si possible le fichier de diagnostic (Paramètres → Appareils et services →
Feux de forêt → ⋮ → Télécharger le diagnostic) ainsi que les logs pertinents.

## Proposer une fonctionnalité

Ouvrez une issue avec le modèle "Proposer une fonctionnalité" avant de soumettre
une pull request importante, afin de discuter de l'approche.

## Développer localement

1. Copiez le dossier `custom_components/feux_de_foret` dans le dossier
   `config/custom_components/` d'une instance Home Assistant de test.
2. Redémarrez Home Assistant après chaque modification du code (les fichiers
   Python ne sont pas rechargés à chaud).
3. Activez les logs de debug pour l'intégration dans `configuration.yaml` :

```yaml
logger:
  default: info
  logs:
    custom_components.feux_de_foret: debug
```

## Style de code

- Suivez le style déjà en place (docstrings courtes, type hints quand pertinent).
- Toute nouvelle option de configuration doit être ajoutée à la fois dans
  `strings.json` et dans `translations/fr.json` + `translations/en.json`.
- Pensez à incrémenter la version dans `manifest.json` et à documenter le
  changement dans la section "Historique des versions" du README.

## Soumettre une pull request

1. Forkez le dépôt et créez une branche depuis `main`.
2. Vérifiez que `hassfest` et la validation HACS passent (voir
   `.github/workflows/validate.yml`, exécuté automatiquement sur chaque PR).
3. Décrivez clairement le changement dans la description de la PR.
