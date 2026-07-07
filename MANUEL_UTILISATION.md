# Manuel utilisateur — CV Agent

> Guide d'utilisation de l'**interface web** de CV Agent pour l'équipe RH.
> Ce document explique comment se servir de l'application au quotidien : consulter
> et trier les candidatures, gérer les offres, lancer une synchronisation, administrer
> les comptes et les réglages.

> ℹ️ **Ce manuel ne traite pas de l'installation ni du déploiement** (serveur, base de
> données, réseau, exécutable). Ces aspects techniques sont couverts par le
> **Manuel de déploiement** (`MANUEL_DEPLOIEMENT.md`), destiné à la personne qui installe
> et maintient le serveur.

---

## Table des matières

1. [Présentation](#1-présentation)
2. [Se connecter](#2-se-connecter)
3. [Rôles et droits](#3-rôles-et-droits)
4. [Navigation générale](#4-navigation-générale)
5. [Liste des candidats (accueil)](#5-liste-des-candidats-accueil)
6. [Fiche d'un candidat](#6-fiche-dun-candidat)
7. [Recherche avancée](#7-recherche-avancée)
8. [Recherche IA (langage naturel)](#8-recherche-ia-langage-naturel)
9. [Offres d'emploi](#9-offres-demploi)
10. [Matching IA (offre ↔ candidat)](#10-matching-ia-offre--candidat)
11. [Alertes](#11-alertes)
12. [Détection de doublons](#12-détection-de-doublons)
13. [Comparaison de candidats](#13-comparaison-de-candidats)
14. [Pipeline de recrutement (kanban)](#14-pipeline-de-recrutement-kanban)
15. [Statistiques RH](#15-statistiques-rh)
16. [Export Excel](#16-export-excel)
17. [Synchronisation (relève des emails)](#17-synchronisation-relève-des-emails)
18. [Administration — Utilisateurs](#18-administration--utilisateurs)
19. [Administration — Paramètres Mail](#19-administration--paramètres-mail)
20. [Administration — Paramètres LLM](#20-administration--paramètres-llm)
21. [Notifications email](#21-notifications-email)
22. [FAQ et dépannage](#22-faq-et-dépannage)
23. [Confidentialité et bonnes pratiques (RGPD)](#23-confidentialité-et-bonnes-pratiques-rgpd)

---

## 1. Présentation

CV Agent automatise le traitement des candidatures reçues par email. À intervalle régulier,
l'application **relève une boîte mail**, **détecte les CV** parmi les pièces jointes, **extrait
automatiquement** les informations clés (nom, coordonnées, poste, expérience, compétences…) et
enregistre chaque candidat dans une base consultable via cette interface web.

L'équipe RH n'a plus qu'à **consulter, trier, annoter et rapprocher** les candidats des offres —
tout le travail de saisie est fait par l'IA.

**À qui s'adresse ce manuel :** toute personne de l'équipe RH qui utilise l'interface (rôles
`rh`, `manager`, `lecture`), ainsi que les administrateurs (`admin`) pour la partie configuration.

**Comment accéder à l'application :** ouvrez un navigateur (Chrome, Edge, Firefox…) et allez à
l'adresse fournie par votre administrateur, par exemple :

```
http://<adresse-du-serveur>:6060
```

> 💡 Rien à installer sur votre poste : l'application s'utilise entièrement dans le navigateur.

---

## 2. Se connecter

### Connexion habituelle

1. Ouvrez l'adresse de l'application.
2. Saisissez votre **email** et votre **mot de passe**.
3. Cliquez sur **Se connecter**.

En cas d'erreur, un message s'affiche. Après **5 tentatives échouées** sur un même compte,
la connexion est **bloquée 30 secondes** (protection contre les essais de mots de passe) — le
message vous indique le délai à attendre. Une connexion réussie remet ce compteur à zéro.

### Toute première utilisation (création du 1er administrateur)

Si l'application vient d'être installée et qu'aucun compte n'existe encore, la page de
**premier lancement** s'affiche automatiquement (`/setup`). Renseignez :

- **Nom complet**
- **Email**
- **Mot de passe** (8 caractères minimum) + confirmation

Cliquez sur **Créer le compte et démarrer**. Ce premier compte est un **administrateur** : il
pourra ensuite créer les autres utilisateurs et configurer l'application.

### Mot de passe oublié

Il n'y a pas d'auto-réinitialisation. **Contactez un administrateur** : il peut vous attribuer
un nouveau mot de passe depuis la page **Utilisateurs** (§18).

### Se déconnecter

Cliquez sur **Se déconnecter** en haut à droite. Votre session expire aussi automatiquement
après plusieurs heures d'inactivité.

---

## 3. Rôles et droits

Chaque compte possède un **rôle** qui détermine ce qu'il peut faire :

| Rôle | Consulter | Modifier les données¹ | Lancer/arrêter une synchro | Administrer² |
|---|:---:|:---:|:---:|:---:|
| **lecture** | ✅ | ❌ | ❌ | ❌ |
| **rh** | ✅ | ✅ | ❌ | ❌ |
| **manager** | ✅ | ✅ | ✅ | ❌ |
| **admin** | ✅ | ✅ | ✅ | ✅ |

¹ *Modifier les données* = changer un statut, écrire un commentaire, ajouter une note ou un
document, créer/modifier des offres, marquer un doublon, gérer les alertes, déplacer une carte
dans le pipeline.

² *Administrer* = gérer les comptes utilisateurs et les paramètres (Mail, LLM).

> Si un bouton d'action n'apparaît pas pour vous, c'est que votre rôle ne l'autorise pas. En
> rôle **lecture**, l'interface est consultable mais les formulaires d'édition sont masqués.

---

## 4. Navigation générale

Une fois connecté, une **barre de menu** en haut donne accès à toutes les rubriques :

| Menu | Rubrique |
|---|---|
| **Tableau de bord** | Vue d'ensemble |
| **Candidats** | Liste et tri des candidats (page d'accueil) |
| **Recherche** | Recherche avancée par critères |
| **Offres** | Gestion des offres d'emploi |
| **Comparer** | Comparaison de 2 à 5 candidats |
| **Doublons** | Détection des candidats en double |
| **Pipeline** | Suivi kanban du processus de recrutement |
| **Matching** | Score de correspondance offre ↔ candidats |
| **Alertes** | Correspondances fortes candidat ↔ offre publiée |
| **Recherche IA** | Recherche en langage naturel |
| **Stats** | Statistiques RH |
| **Cycles** | Historique et déclenchement des synchronisations |
| **Utilisateurs** *(admin)* | Gestion des comptes |
| **Param. Mail** *(admin)* | Réglages boîte mail, planificateur, notifications |
| **Param. LLM** *(admin)* | Réglages moteur d'IA |

À droite de la barre :

- 🌗 **Bouton thème** : bascule entre thème clair et sombre (mémorisé sur votre navigateur).
- 👤 **Votre nom + rôle**.
- **Se déconnecter**.

---

## 5. Liste des candidats (accueil)

C'est la page centrale de l'application (menu **Candidats**). Elle affiche tous les candidats
détectés, avec des outils de tri.

### En-tête

- **Bandeau de compteurs** : nombre total de candidats et répartition par statut, plus la date
  du dernier cycle réussi et le nombre de CV qu'il a détectés.
- **▶ Lancer un cycle** *(manager/admin)* : déclenche une synchronisation de la boîte mail
  (voir §17). La case **à zéro** est à n'utiliser qu'exceptionnellement (elle efface tout et
  réanalyse — voir l'avertissement au §17).
- **📥 Exporter Excel** : télécharge la liste au format Excel (voir §16).

### Filtres

Une barre permet de restreindre la liste :

- **🔍 Recherche libre** : nom, email ou compétence.
- **Statut** : menu déroulant (Tous statuts, Nouveau, À contacter…).
- **Poste** : filtre par intitulé de poste recherché.
- **Filtrer** pour appliquer, **Réinitialiser** pour tout effacer.

### Tableau

Colonnes : **ID**, **Reçu** (date/heure), **Candidat** (nom + email, cliquable), **Poste**,
**Exp.** (années d'expérience), **Compétences** (aperçu), **Statut**, et un bouton **Voir**.

- **Changer un statut** *(rh/manager/admin)* : utilisez le menu déroulant dans la colonne
  **Statut**. L'enregistrement est **immédiat**, sans rechargement de page.
- **Ouvrir une fiche** : cliquez sur le nom du candidat ou sur **Voir**.

### Statuts disponibles

`Nouveau` · `À contacter` · `Entretien planifié` · `Refusé` · `Embauché` · `Doublon`

---

## 6. Fiche d'un candidat

Accessible en cliquant sur un candidat. La page est en deux parties : les **informations** à
gauche, l'**aperçu du CV (PDF)** à droite.

### Informations extraites

Tous les champs récupérés automatiquement depuis le CV : expéditeur, email, téléphone, poste
recherché, spécialité, wilaya/ville, années d'expérience, disponibilité, salaire souhaité,
niveau d'étude, diplôme, université, compétences techniques, logiciels, soft skills, langues,
certifications, entreprises, permis, résumé. Un lien **📄 fichier** ouvre le PDF d'origine.

Si le CV décrit un parcours détaillé, une section **Expériences professionnelles** liste les
postes occupés.

> Un champ vide s'affiche « — » : soit l'information n'était pas dans le CV, soit l'IA ne l'a
> pas trouvée. Vous pouvez toujours vérifier dans l'aperçu du PDF à droite.

### Éditer le statut et les commentaires *(rh/manager/admin)*

Un formulaire permet de :

- Choisir le **statut** du candidat.
- Écrire des **commentaires RH** (notes libres : impressions, suite à donner…).

Cliquez sur **💾 Enregistrer**. En rôle **lecture**, ces informations sont affichées mais non
modifiables.

### Résumé IA

Section **Résumé IA** : cliquez sur **Générer la fiche IA** pour produire une synthèse
professionnelle du profil (résumé, expérience totale, compétences clés, forces, axes
d'amélioration, recommandations). La génération prend quelques secondes. Un bouton
**Régénérer** permet de la recalculer. Si l'IA est momentanément indisponible, un message
s'affiche et la fiche déjà enregistrée reste visible.

### Notes internes

Fil de **notes internes** partagées par l'équipe : chaque note est horodatée et signée du nom
de son auteur. Saisissez votre note et cliquez sur **Ajouter**. Utile pour tracer les échanges
(« relancé le 12/07 », « entretien positif »…).

### Documents

Section **Documents** pour attacher des pièces au candidat (diplôme, certificat, portfolio…) :

- Choisissez un fichier, sélectionnez un **type**, cliquez sur **Ajouter**.
- Chaque document peut être **téléchargé** ou **supprimé**.

> Taille maximale par fichier : 20 Mo.

---

## 7. Recherche avancée

Menu **Recherche**. Recherche multicritères précise sur les champs des candidats.

1. Remplissez un ou plusieurs champs (poste, spécialité, compétences, langue, ville, etc.) et,
   au besoin, une **expérience minimale** (en années).
2. Choisissez l'**opérateur logique** :
   - **AND** : tous les critères doivent être remplis (résultats les plus restrictifs).
   - **OR** : au moins un critère suffit (résultats les plus larges).
   - **NOT** : exclut les candidats correspondant aux critères.
3. Cliquez sur **🔍 Rechercher**.

Les résultats s'affichent dans un tableau (jusqu'à 500 lignes). Cliquez sur un candidat pour
ouvrir sa fiche. **Réinitialiser** vide le formulaire.

---

## 8. Recherche IA (langage naturel)

Menu **Recherche IA**. Décrivez le profil recherché **en français courant** ; l'IA traduit
votre demande en filtres et interroge la base.

Exemple :

> *« Trouve-moi un ingénieur réseau Cisco avec plus de 5 ans d'expérience parlant anglais »*

1. Saisissez votre phrase dans la zone de texte.
2. Cliquez sur **✨ Rechercher**.

L'application affiche d'abord les **filtres interprétés** (poste, spécialité, expérience,
compétences, langues…) sous forme d'étiquettes, puis la liste des candidats correspondants.

> Si l'IA n'extrait aucun critère exploitable, reformulez avec des termes plus précis (métier,
> technologies, niveau d'expérience). Pour un contrôle exact des critères, préférez la
> **Recherche avancée** (§7).

---

## 9. Offres d'emploi

Menu **Offres**. Gérez le catalogue de postes à pourvoir ; les offres alimentent le **Matching**
(§10) et les **Alertes** (§11).

### Liste

Tableau des offres (titre, département, lieu, statut, date de mise à jour). Un filtre par
**statut** est disponible. Statuts d'une offre : **Brouillon**, **Publiée**, **Archivée**.

### Créer une offre *(rh/manager/admin)*

Bouton **➕ Nouvelle offre**, puis renseignez : titre, département, lieu, expérience minimale,
niveau d'étude, **compétences requises**, description. Enregistrez.

> 💡 Les **compétences requises** sont déterminantes pour le Matching : listez-les clairement
> (séparées par des virgules).

### Fiche d'une offre

Depuis la liste, ouvrez une offre pour :

- **✏️ Modifier** ses informations.
- **📢 Publier** : la rend « Publiée » — condition pour générer des **alertes** automatiques.
- **🗄️ Archiver** : la retire des offres actives.
- **🗑️ Supprimer** (définitif, avec confirmation).

---

## 10. Matching IA (offre ↔ candidat)

Menu **Matching**. Calcule un **score de correspondance** (sur 100) entre une offre et chacun
de vos candidats. Le calcul est **local et déterministe** (aucun appel externe, fonctionne
hors-ligne).

1. Choisissez une offre dans la liste → **Voir le matching**.
2. Le tableau classe les candidats par score décroissant, avec :
   - le **rang** et le **score /100** ;
   - une **barre de compatibilité** visuelle ;
   - les **points forts** (compétences qui matchent) ;
   - les **compétences manquantes** par rapport à l'offre.
3. Cliquez sur un candidat pour ouvrir sa fiche.

Le bouton **↻ Recalculer** relance le calcul (utile après avoir modifié l'offre ou reçu de
nouveaux candidats).

> Le classement est mis en cache au premier affichage ; utilisez **Recalculer** pour le
> rafraîchir.

---

## 11. Alertes

Menu **Alertes**. Une **alerte** est créée automatiquement lorsqu'un candidat obtient un score
**≥ 60/100** vis-à-vis d'une offre **publiée**. C'est le moyen de repérer sans effort les bons
profils pour vos postes ouverts.

- Les alertes **non lues** apparaissent en **gras** ; le compteur en titre indique leur nombre.
- Chaque ligne renvoie vers la **fiche du candidat** et vers le **matching de l'offre**.
- **Marquer lu** (par alerte) ou **✓ Tout marquer comme lu**.
- **🔄 Recalculer** : relance la recherche de correspondances pour **tous** les candidats et
  **toutes** les offres publiées — à faire après avoir publié de nouvelles offres ou reçu de
  nouveaux CV.

> Aucune alerte n'apparaît tant qu'aucune offre n'est **publiée**. Publiez vos offres (§9) puis
> cliquez sur **Recalculer**.

---

## 12. Détection de doublons

Menu **Doublons**. Regroupe les candidats susceptibles d'être en double, par **email**,
**téléphone** ou **nom**. Dans chaque groupe, le candidat le plus ancien (plus petit ID) est
considéré comme l'**original**.

Pour marquer un candidat comme doublon d'un autre : cliquez sur **Marquer comme doublon de #X**.
Le candidat prend alors le statut de doublon rattaché à l'original.

> Aucun candidat n'est supprimé automatiquement : la détection ne fait que **signaler** les
> doublons potentiels ; la décision reste manuelle.

---

## 13. Comparaison de candidats

Menu **Comparer**. Met en regard **2 à 5 candidats**, un par colonne, critère par critère.

1. Cochez les candidats à comparer dans la liste, puis **Comparer**.
2. Le tableau affiche côte à côte : poste, spécialité, wilaya, niveau d'étude, diplôme,
   **années d'expérience** (la meilleure valeur est mise en évidence), compétences, langues,
   soft skills, certifications, disponibilité, salaire souhaité, statut.
3. **Modifier la sélection** permet de revenir au choix des candidats.

Idéal pour départager une short-list avant entretien.

---

## 14. Pipeline de recrutement (kanban)

Menu **Pipeline**. Visualise les candidats sous forme de **tableau kanban**, une colonne par
étape du processus de recrutement.

- Chaque candidat est une **carte**.
- **Glissez-déposez** une carte d'une colonne à l'autre pour faire avancer le candidat dans le
  processus *(rh/manager/admin)*. Le changement est **enregistré automatiquement**.
- Cliquez sur **Voir la fiche** sur une carte pour ouvrir le candidat.

En cas d'échec d'enregistrement (réseau), la carte revient à sa position d'origine et un
message vous invite à réessayer.

---

## 15. Statistiques RH

Menu **Stats**. Tableau de bord analytique du recrutement :

- **Indicateurs clés** : temps moyen de recrutement (jours), taux de recrutement (%), taux de
  refus (%), nombre total de candidats.
- **Répartition par statut** (Nouveau, À contacter, Embauché…).
- **Graphiques** : évolution mensuelle des candidatures, candidats par métier, compétences les
  plus demandées dans vos offres.

Les statistiques se remplissent au fur et à mesure que des candidats sont analysés et que des
statuts sont mis à jour.

---

## 16. Export Excel

Depuis la **liste des candidats** (§5), bouton **📥 Exporter Excel**. Le fichier
(`candidats_AAAAMMJJ_HHMM.xlsx`) se télécharge immédiatement et contient une ligne par candidat
avec l'ensemble des champs (identité, coordonnées, poste, expérience, diplômes, compétences,
langues, statut, commentaires RH, etc.).

**À retenir :**

- L'export est un **instantané** au moment du clic.
- Les modifications faites **dans le fichier Excel ne remontent pas** dans l'application : la
  référence reste toujours l'interface web.
- Générez l'export juste avant de le transmettre pour disposer des données à jour.

---

## 17. Synchronisation (relève des emails)

La **synchronisation** (aussi appelée « cycle ») est l'opération qui va relever la boîte mail,
détecter les nouveaux CV et les ajouter à la base. Elle se produit de deux façons :

1. **Automatiquement**, à intervalle régulier (60 minutes par défaut), sans intervention.
2. **Manuellement**, via le bouton **▶ Lancer un cycle** *(manager/admin)*, présent sur la
   liste des candidats et sur la page **Cycles**.

> 🔎 **La synchronisation s'exécute sur le serveur**, pas sur votre poste. Vous pouvez cliquer
> depuis n'importe quel navigateur : c'est le serveur qui relève la boîte mail et lance
> l'analyse. Vous n'avez donc **aucun paramétrage de messagerie à faire sur votre machine**.

### Suivre les cycles (menu **Cycles**)

La page **Cycles** affiche l'historique : identifiant, heures de début/fin, source
(`scheduler` = automatique, `manual` = bouton, `cli` = ligne de commande), nombre d'emails lus,
CV détectés, statut (`success`, `failed`, `running`) et message d'erreur éventuel.

- Un bandeau indique si **un cycle est en cours**.
- Pendant un cycle, **■ Arrêter le cycle** *(manager/admin)* permet de l'interrompre proprement.

### Option « Recommencer à zéro » ⚠️

La case **Recommencer à zéro** (à côté du bouton Lancer) **efface tous les candidats** et
**réanalyse tous les emails** de la fenêtre configurée. À réserver à un cas exceptionnel (par
exemple après un mauvais paramétrage initial). Une confirmation est demandée. **En usage normal,
ne cochez jamais cette case.**

> L'administrateur dispose aussi, sur la page Cycles, d'un bouton **🗑 Vider historique +
> candidats** — action **irréversible** réservée à la maintenance.

---

## 18. Administration — Utilisateurs

*Réservé au rôle **admin*** (menu **Utilisateurs**).

### Créer un compte

Renseignez **email**, **nom complet**, **mot de passe** et **rôle** (`rh`, `manager`,
`lecture seule` ou `admin`), puis **Créer**.

> Communiquez les identifiants par un **canal sécurisé** (en personne, messagerie chiffrée) —
> jamais par email en clair.

### Modifier un compte

Sur chaque ligne, vous pouvez changer le **nom**, le **rôle** et l'état **actif/désactivé**.
Pour changer le mot de passe, saisissez-en un nouveau (laisser vide = mot de passe inchangé).
Cliquez sur **💾 Modifier**.

### Désactiver plutôt que supprimer

Pour un collaborateur qui quitte l'équipe, préférez le passer en **désactivé** : il ne pourra
plus se connecter, mais l'historique (notes signées, etc.) est conservé. La **suppression**
(🗑) est définitive.

### Garde-fous

Pour éviter de vous verrouiller hors de l'application, il est **impossible** de :

- supprimer **votre propre** compte ;
- supprimer ou désactiver le **dernier administrateur actif**.

---

## 19. Administration — Paramètres Mail

*Réservé au rôle **admin*** (menu **Param. Mail**). Toutes les modifications sont appliquées
immédiatement. Pour les mots de passe, **laisser vide conserve** la valeur actuelle.

| Réglage | À renseigner |
|---|---|
| **Serveur IMAP** | Adresse du serveur de réception (ex. `imap.gmail.com`). |
| **Port IMAP** | Généralement `993`. |
| **Utilisateur (email)** | L'adresse de la boîte de candidatures. |
| **Mot de passe d'application** | Pour Gmail : un **mot de passe d'application** (pas le mot de passe habituel du compte). |
| **Dossier IMAP** | Dossier à relever (ex. `INBOX`). |
| **Profondeur historique (jours)** | Ancienneté maximale des emails relevés. |
| **Max emails / cycle** | Nombre maximal d'emails traités par synchronisation. |
| **Intervalle planificateur (min)** | Fréquence des synchronisations automatiques. |
| **Planificateur activé** | `true` pour activer la relève automatique, `false` pour ne relever qu'à la main. |
| **Notifications email** | `true`/`false` (voir §21). |
| **Destinataires** | Emails prévenus, séparés par des virgules. |
| **Serveur / Port / Sécurité SMTP** | Serveur d'envoi pour les notifications. |
| **Utilisateur / Mot de passe SMTP** | Identifiants d'envoi. |
| **Expéditeur (From)** | Adresse affichée comme expéditeur des notifications. |

Deux boutons de test évitent les erreurs de saisie :

- **📬 Tester la connexion à la boîte mail** : vérifie les identifiants IMAP.
- **✉️ Tester SMTP** : envoie un email de test aux destinataires renseignés.

> Les mots de passe et clés sont **chiffrés** dans la base ; ils ne s'affichent jamais en clair.

---

## 20. Administration — Paramètres LLM

*Réservé au rôle **admin*** (menu **Param. LLM**). Configure le moteur d'intelligence
artificielle utilisé pour détecter et analyser les CV.

### Choix du moteur

- **💻 Local (Ollama)** : l'IA tourne sur le serveur, **aucune donnée ne sort** de la machine.
- **☁️ Cloud (OpenRouter / Gemini / OpenAI…)** : l'IA est appelée via un service en ligne
  (nécessite une clé API). Dans ce mode, le **contenu des CV est transmis au prestataire** —
  à n'utiliser qu'en connaissance de cause.

Selon le moteur choisi, les champs correspondants s'affichent :

| Moteur | Réglages |
|---|---|
| **Ollama** | Modèle, URL du serveur Ollama, délai d'attente (timeout). |
| **Cloud** | URL de base (compatible OpenAI), modèle, **clé API**, timeout. |

### Réglages communs

- **Seuil de confiance CV (0-1)** : niveau à partir duquel un email est considéré comme
  contenant un CV. Plus il est bas, plus l'application est « inclusive » (au risque de faux
  positifs). Valeur typique : `0.6`.
- **Max chars PDF envoyés au LLM** : quantité de texte du CV transmise à l'IA.

Un bouton **🔌 Tester** valide la connexion au moteur (serveur + modèle, ou service cloud).

> Après avoir modifié le moteur, **testez** avant de lancer une synchronisation, puis
> vérifiez sur un premier cycle que les CV sont bien détectés.

---

## 21. Notifications email

Si elles sont activées (§19), CV Agent peut **prévenir par email** les destinataires configurés :

- à l'arrivée de **nouveaux candidats** lors d'une synchronisation ;
- lorsqu'une **alerte** (correspondance forte candidat ↔ offre publiée) est détectée.

C'est utile pour être réactif sans devoir consulter l'application en permanence. Les
notifications sont **facultatives** et « best effort » : un échec d'envoi n'interrompt jamais le
traitement des candidatures.

---

## 22. FAQ et dépannage

**Je ne vois aucun candidat / ma liste est vide.**
Vérifiez qu'une synchronisation a bien eu lieu (page **Cycles** : un cycle `success` avec des CV
détectés). Sinon, demandez à un manager/admin de **Lancer un cycle**. Vérifiez aussi vos
**filtres** (bouton **Réinitialiser** sur la liste des candidats).

**Un email de candidature n'apparaît pas dans la liste.**
Plusieurs causes possibles : la pièce jointe n'est pas un CV (ou n'est pas un `.pdf`/`.docx`),
le CV est un **PDF scanné** (image sans texte : non lu), ou l'email est plus ancien que la
**profondeur historique** configurée. Consultez la page **Cycles** pour le nombre d'emails lus,
et au besoin demandez à un admin de vérifier les **Paramètres Mail**.

**La génération de la fiche « Résumé IA » affiche une erreur.**
Le moteur d'IA est momentanément indisponible. Réessayez dans quelques instants ; la fiche
précédemment enregistrée reste visible. Si le problème persiste, prévenez votre administrateur
(§20, bouton de test).

**Le changement de statut ne se sauvegarde pas / les formulaires sont absents.**
Vous êtes probablement en rôle **lecture** (consultation seule). Demandez le rôle adéquat à un
administrateur.

**« Un cycle est déjà en cours ».**
Une synchronisation tourne déjà : attendez qu'elle se termine (page **Cycles**), ou utilisez
**■ Arrêter le cycle**.

**Aucune alerte n'apparaît.**
Vérifiez que des offres sont **Publiées** (§9), puis cliquez sur **🔄 Recalculer** dans la page
**Alertes**.

**Je n'arrive pas à me connecter (compte bloqué).**
Après 5 échecs, la connexion est bloquée **30 secondes** : attendez le délai indiqué et
réessayez avec le bon mot de passe. En cas d'oubli, contactez un administrateur.

**L'application est-elle accessible depuis chez moi ?**
Par défaut, elle n'est accessible que sur le **réseau local**. Pour un accès distant, voyez avec
votre administrateur (VPN). Il n'y a rien à installer : uniquement un navigateur.

---

## 23. Confidentialité et bonnes pratiques (RGPD)

Les CV contiennent des **données personnelles**. Quelques règles simples :

- **Traitement local par défaut** : avec le moteur IA **local (Ollama)**, aucune donnée de CV
  ne sort du serveur. Le mode **cloud** transmet en revanche le contenu des CV à un prestataire
  externe — à n'activer que si votre organisation l'autorise.
- **Limitez la diffusion des exports Excel** : un export contient l'ensemble des données
  candidats. Ne le transmettez qu'aux personnes habilitées, par un canal sécurisé, et ne le
  conservez pas plus que nécessaire.
- **Finalité et durée** : n'utilisez les données que pour le recrutement, et purgez les
  candidatures obsolètes conformément à la politique de votre organisation.
- **Comptes** : un compte par personne, mot de passe robuste, **déconnexion** sur un poste
  partagé. Désactivez (plutôt que supprimer) les comptes des personnes qui quittent l'équipe.
- **Confidentialité des identifiants** : ne partagez pas votre mot de passe ; signalez tout
  accès suspect à votre administrateur.

> Pour les aspects techniques de sécurité (chiffrement des secrets, exposition réseau,
> sauvegardes), voir le **Manuel de déploiement**.

---

*Manuel utilisateur — CV Agent. Rédigé pour l'équipe RH. Pour l'installation, la configuration
serveur et la maintenance, se reporter au Manuel de déploiement (`MANUEL_DEPLOIEMENT.md`).*
