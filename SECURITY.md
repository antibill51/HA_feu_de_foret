# Politique de sécurité

## Signaler une vulnérabilité

Si vous découvrez une vulnérabilité de sécurité dans cette intégration
(par exemple une fuite de données sensibles, une injection, ou un problème
lié aux appels réseau vers feuxdeforet.fr), merci de **ne pas** ouvrir une
issue publique.

Contactez plutôt directement le mainteneur du dépôt via GitHub (message privé
ou email si disponible sur le profil), en décrivant :
- La nature du problème
- Les étapes pour le reproduire
- L'impact potentiel

Nous nous engageons à répondre dans les meilleurs délais et à publier un
correctif accompagné d'une entrée dans le changelog une fois le problème résolu.

## Portée

Cette intégration ne stocke aucune donnée personnelle sensible. Les seules
informations transmises à des services tiers sont :
- Les coordonnées géographiques de vos zones surveillées, à `feuxdeforet.fr`
  (nécessaire au fonctionnement du service)
- Si vous activez les notifications Telegram, les messages sont envoyés via
  votre propre configuration `notify` existante — aucune clé ni identifiant
  n'est géré par cette intégration elle-même.
