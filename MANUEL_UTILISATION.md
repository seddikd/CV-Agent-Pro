# Manuel utilisateur — CV Agent

> Guide d'utilisation de l'**interface web** de CV Agent pour l'équipe RH.
> Ce document explique comment se servir de l'application au quotidien : consulter
> et trier les candidatures, gérer les offres, lancer une synchronisation, administrer
> les comptes et les réglages.

> ℹ️ **Ce manuel ne traite pas de l'installation ni du déploiement** (serveur, base de
> données, réseau, exécutable). Ces aspects techniques sont couverts par le
> **Manuel de déploiement**, destiné à la personne qui installe
> et maintient le serveur.

---

## Table des matières

1. [Présentation](#1-présentation)
2. [Se connecter](#2-se-connecter)
3. [Rôles et droits](#3-rôles-et-droits)
4. [Navigation générale](#4-navigation-générale)
4bis. [Tableau de bord](#4bis-tableau-de-bord)
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
17bis. [Import de fichiers Outlook (PST / OST)](#17bis-import-de-fichiers-outlook-pst--ost)
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
| **Import Outlook** *(manager/admin)* | Import de CV depuis un fichier `.pst` / `.ost` |
| **Utilisateurs** *(admin)* | Gestion des comptes |
| **Param. Mail** *(admin)* | Réglages boîte mail, planificateur, notifications |
| **Param. LLM** *(admin)* | Réglages moteur d'IA |

À droite de la barre : une **cloche** vers les alertes, puis **votre nom et votre rôle**.
Cliquer dessus ouvre un menu qui regroupe :

- l'**administration** (Cycles, Import Outlook, et pour un admin : Utilisateurs, Modèles
  d'email, RGPD, Param. Mail, Param. LLM) ;
- **Thème clair / sombre** — la bascule est mémorisée sur votre navigateur, et l'icône montre
  le thème vers lequel vous basculerez (un soleil quand vous êtes en sombre) ;
- **Vue par onglets / Vue barre latérale** — deux présentations de la même application, au
  choix ; le réglage est propre à votre navigateur ;
- **Se déconnecter**.

---

## 4bis. Tableau de bord

Menu **Tableau de bord**. C'est la vue d'ensemble du vivier, distincte des **Stats** (§15) qui,
elles, mesurent la performance du recrutement.

- **Quatre indicateurs** en haut : CV au total, nouveaux sur 7 jours, entretiens planifiés,
  embauchés.
- **La répartition par statut**, juste en dessous. Chaque pastille est **cliquable** et ouvre la
  liste des candidats filtrée sur ce statut — c'est le chemin le plus court pour attaquer les
  « À contacter » du jour.
- **Six graphiques** : répartition des CV par spécialité, par métier, par wilaya, par niveau
  d'étude, par années d'expérience, et le top 15 des compétences. Au-delà d'une dizaine de
  catégories, le reste est regroupé sous « Autres ».
- **Entretiens à venir** et **Activité récente** dans la colonne de droite, avec des horodatages
  relatifs (« aujourd'hui », « demain », « hier ») et un accès direct à chaque fiche.

Si aucun CV n'a encore été analysé, la page l'indique et propose les deux façons de commencer :
relever la boîte mail ou importer une archive Outlook.

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

### Marquer les doublons en lot *(rh/manager/admin)*

Plutôt que de traiter les doublons un par un, vous pouvez en **sélectionner plusieurs** et les
marquer en une seule fois :

1. **Cochez** les candidats à considérer comme doublons. Chaque case indique déjà de quel
   original le candidat deviendra le doublon (« → doublon de #X »). Les **originaux** et les
   candidats **déjà marqués** n'ont pas de case.
2. Pour aller plus vite : **Sélectionner le groupe** coche tous les doublons d'un groupe, et
   **Tout sélectionner** (barre du haut) coche l'ensemble des groupes.
3. La barre du haut affiche le **nombre de candidats sélectionnés**. Cliquez sur
   **🏷️ Marquer la sélection comme doublons** puis confirmez.

Chaque candidat marqué prend le statut **Doublon**, rattaché à son original. Vous pouvez aussi
marquer un seul candidat : cochez-le simplement, puis validez.

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
- La croix en haut à droite d'une carte **retire le candidat du pipeline** ; il reste dans la
  base et redevient disponible dans la recherche.
- Le champ de recherche au-dessus des colonnes cherche dans le **vivier** (les candidats hors
  pipeline) : cliquez sur un résultat pour l'engager directement en « Présélection ».

### Le motif de refus est obligatoire

Déposer une carte dans la colonne **Refusé** ouvre une fenêtre qui **exige un motif**. Ce n'est
pas une formalité : le motif reste attaché à la fiche du candidat et sera visible lors d'une
consultation ultérieure — c'est ce qui permet, des mois plus tard, de dire pourquoi une
candidature n'a pas abouti. Tant que le champ est vide, la validation est refusée ; **Annuler**
laisse la carte dans sa colonne d'origine.

### Au clavier

Le glisser-déposer n'est pas la seule voie. Une carte s'atteint avec **Tab**, puis :

| Touche | Effet |
|---|---|
| **←** et **→** | Déplacent la carte d'une colonne vers la gauche ou la droite |
| **Suppr** | Retire le candidat du pipeline (une confirmation est demandée) |

Chaque déplacement est annoncé aux lecteurs d'écran.

En cas d'échec d'enregistrement (réseau), la carte revient à sa position d'origine et un
message vous invite à réessayer, sans que rien ne soit perdu.

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
2. **Manuellement**, via le bouton **Lancer un cycle** *(manager/admin)*, présent sur la
   liste des candidats et sur la page **Cycles**.

> 🔎 **La synchronisation s'exécute sur le serveur**, pas sur votre poste. Vous pouvez cliquer
> depuis n'importe quel navigateur : c'est le serveur qui relève la boîte mail et lance
> l'analyse. Vous n'avez donc **aucun paramétrage de messagerie à faire sur votre machine**.

### Suivre un cycle en direct

Depuis la page **Cycles**, une carte affiche l'avancement du cycle en cours et **se met à jour
toute seule** : inutile de recharger la page. Elle suit les quatre moments du traitement.

| Moment | Ce que la carte affiche |
|---|---|
| **Relève** | « Connexion à la boîte mail et recherche des messages à traiter… ». Le nombre d'emails à traiter n'est pas encore connu : la barre défile sans pourcentage. |
| **Traitement** | Le pourcentage, la barre remplie, le nombre d'emails **restants** sur le total, une **estimation du temps restant**, et le compteur de CV détectés qui monte au fil de l'analyse. |
| **Finalisation** | « Calcul des alertes, envoi des notifications et rangement de la boîte… ». Tous les emails sont traités, il n'y a plus rien à décompter. |
| **Au repos** | Le dernier cycle terminé, l'heure à laquelle il s'est achevé et ses chiffres — ou son message d'erreur s'il a échoué. |

Quelques précisions utiles :

- **L'estimation n'apparaît qu'après quelques emails traités.** Avant, la moyenne est faussée par
  le temps de connexion et donnerait un chiffre absurde. Elle reste volontairement prudente : mieux
  vaut finir plus tôt qu'annoncé.
- **La même carte apparaît sur la liste des candidats** dès qu'un cycle démarre, y compris
  déclenché automatiquement. Vous n'avez pas besoin d'être sur la page Cycles pour le voir passer.
- **Arrêter le cycle** *(manager/admin)* se trouve **dans la carte elle-même**, au contact de ce
  qu'il arrête. L'arrêt est coopératif : l'email en cours d'analyse se termine, puis le cycle
  s'interrompt. Le bouton disparaît pendant la finalisation, étape où il n'y a plus rien à arrêter.
- Si la carte affiche **« Cycle interrompu »** en rouge, c'est qu'un cycle est marqué en cours en
  base alors qu'il ne tourne plus — l'application a redémarré pendant son exécution. Le bouton
  **Nettoyer ce cycle** libère la place ; aucun email déjà traité n'est repris.

### L'historique des cycles

Sous la carte, le tableau liste les cycles passés : identifiant, heures de début et de fin,
**source** (Automatique, Manuel, Ligne de commande, Import Outlook), nombre d'emails **traités**,
CV détectés, **statut** (Réussi, Échec, Arrêté, En cours) et message d'erreur éventuel.

Les horodatages sont exprimés par rapport à aujourd'hui — « aujourd'hui à 08:14 », « hier à
18:40 », « 27/08 à 09:12 ». Survolez-en un pour lire la date et l'heure exactes.

### Option « Recommencer à zéro » ⚠️

La case **Recommencer à zéro** (à côté du bouton Lancer) **efface tous les candidats** et
**réanalyse tous les emails** de la fenêtre configurée. À réserver à un cas exceptionnel (par
exemple après un mauvais paramétrage initial). Une confirmation est demandée. **En usage normal,
ne cochez jamais cette case.**

> L'administrateur dispose aussi, sur la page Cycles, d'un bouton **Vider historique +
> candidats** — action **irréversible** réservée à la maintenance.

### Rangement des mails en fin de cycle

Si l'option **Ranger automatiquement les mails traités** est activée (§19), chaque cycle se
termine par une passe de rangement : les mails analysés quittent la boîte de réception pour
les dossiers configurés. Deux garde-fous :

- un rangement qui échoue (dossier supprimé, coupure réseau, droits insuffisants) **ne fait
  jamais échouer le cycle** — les mails restent simplement en place et seront rangés au cycle
  suivant ou via le bouton manuel ;
- si vous **arrêtez** le cycle avec **Arrêter le cycle**, la passe de rangement est **sautée**.

---

## 17bis. Import de fichiers Outlook (PST / OST)

*Menu **📥 Import Outlook*** *(manager/admin)*. En complément de l'IMAP, vous pouvez
importer les CV contenus dans une **archive Outlook** `.pst` ou `.ost`. Un tel fichier
est un **instantané** : il est parcouru **une fois**, puis le traitement habituel
s'applique (détection de CV, extraction, dédup). Les messages **sans pièce jointe
PDF/DOCX** sont ignorés, et **réimporter le même fichier ne crée pas de doublons**.

Trois façons de fournir le fichier :

1. **Téléverser** (section 1 de la page) : pratique pour un fichier de taille modérée.
2. **Déposer dans le dossier serveur** puis choisir le fichier dans la liste (section 2).
   Recommandé pour les **gros fichiers** (plusieurs Go) : en Docker, déposez-les dans le
   dossier monté (par défaut `./import`).
3. **Chemin serveur** (section 3) : indiquez le chemin absolu d'un fichier accessible par
   le serveur.

Pour chaque fichier, le bouton **🔍 Tester** vérifie qu'il est lisible et compte les
messages exploitables ; **▶ Importer** lance le traitement. Le **suivi et les résultats**
apparaissent dans la page **Cycles** (source `import_outlook`), comme un cycle normal —
vous pouvez d'ailleurs l'**arrêter** depuis cette page.

> **OST** : le format de cache hors-ligne est lu au mieux. Certains OST récents
> (chiffrés / liés au profil) peuvent échouer : convertissez-les alors en PST depuis
> Outlook avant l'import.

### Ranger les mails traités — import PST/OST *(manager/admin)*

> 📬 Pour la **boîte IMAP**, le rangement équivalent se règle dans **§19 — Paramètres Mail**
> (automatique en fin de cycle ou bouton manuel) et ne nécessite **pas** Outlook. La section
> ci-dessous ne concerne que les fichiers `.pst` / `.ost`.

Après un import, le bouton **📁 Ranger les traités** (sur chaque ligne de fichier)
déplace **tous les mails porteurs d'un CV** (PDF/DOCX) vers un dossier dédié — par
défaut **Traités**, dont le nom vous est demandé — afin de garder la boîte propre et de
distinguer d'un coup d'œil ce qui a déjà été traité. Une confirmation est demandée.

Le comportement dépend du type de fichier :

- **`.pst`** : les mails sont déplacés **à l'intérieur du fichier** ; aucune incidence sur
  un serveur.
- **`.ost`** : un OST est le **cache d'un compte** Exchange / Microsoft 365 et ne peut pas
  être ouvert isolément. L'opération s'applique donc à la **boîte réelle** du compte
  (qui doit être configuré dans Outlook sur ce poste) et **se synchronise vers le serveur**.

Les dossiers système (**Éléments envoyés**, **Éléments supprimés**, **Brouillons**, **Boîte
d'envoi**, **Courrier indésirable**) ne sont jamais touchés.

> ⚠️ **Nécessite Microsoft Outlook installé** sur le serveur (composant `win32com`) — cette
> contrainte vaut **uniquement** pour le rangement des fichiers PST/OST, pas pour celui de la
> boîte IMAP (§19), qui n'a besoin de rien d'autre que la connexion à votre messagerie. Sans
> Outlook, le bouton est **grisé** : le lecteur `pypff` seul est en lecture seule et ne peut
> pas déplacer de message. Pour un `.ost`, le déplacement modifie la vraie boîte : cette
> action **n'est pas annulable en masse**, vérifiez le dossier de destination avant de valider.

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

> **Tout fournisseur IMAP est accepté** : Gmail, Outlook / Office 365, OVH, Zoho, ou un
> serveur de messagerie interne — pas seulement Gmail.

| Réglage | À renseigner |
|---|---|
| **Serveur IMAP** | Adresse du serveur de réception (ex. `imap.gmail.com`, `outlook.office365.com`, `ssl0.ovh.net`…). |
| **Port IMAP** | Selon la sécurité : `993` en SSL, `143` en STARTTLS/Aucune. |
| **Sécurité IMAP** | `SSL` (port 993, le plus courant) / `STARTTLS` (port 143) / `Aucune` (port 143, non chiffré — à éviter). |
| **Utilisateur (email)** | L'adresse de la boîte de candidatures. |
| **Mot de passe** | Le mot de passe de la boîte. Certains fournisseurs (Gmail, Outlook) exigent un **mot de passe d'application** dédié, pas le mot de passe habituel du compte. |
| **Dossier IMAP** | Dossier à relever (ex. `INBOX`). |
| **Ranger automatiquement les mails traités en fin de cycle** | ✅ *Activé* / ⬜ *Désactivé* (**désactivé par défaut**). Activé, chaque synchronisation se termine en déplaçant les mails **déjà analysés** vers les deux dossiers ci-dessous. |
| **Rangement : dossier des CV** | Dossier d'arrivée des mails ayant produit un candidat (défaut **Traités**). |
| **Rangement : dossier des non-CV (vide = laisser en place)** | Dossier d'arrivée des mails analysés mais écartés (pas une candidature). **Laissé vide**, ces mails ne bougent pas. |
| **Profondeur historique (jours)** | Ancienneté maximale des emails relevés. |
| **Max emails / cycle** | Nombre maximal d'emails traités par synchronisation. |
| **Intervalle planificateur (min)** | Fréquence des synchronisations automatiques. |
| **Planificateur activé** | `true` pour activer la relève automatique, `false` pour ne relever qu'à la main. |
| **Notifications email** | `true`/`false` (voir §21). |
| **Destinataires** | Emails prévenus, séparés par des virgules. |
| **Serveur / Port / Sécurité SMTP** | Serveur d'envoi pour les notifications. |
| **Utilisateur / Mot de passe SMTP** | Identifiants d'envoi. |
| **Expéditeur (From)** | Adresse affichée comme expéditeur des notifications. |

Trois boutons complètent la page :

- **📬 Tester la connexion à la boîte mail** : vérifie les identifiants IMAP.
- **✉️ Tester SMTP** : envoie un email de test aux destinataires renseignés.
- **📁 Ranger les mails traités maintenant** : lance le rangement **immédiatement**, sans
  attendre le prochain cycle.

### Le rangement des mails traités

Il déplace, **dans votre boîte mail**, les messages que l'application a **déjà analysés** :
les CV vers le dossier des CV, les mails écartés vers celui des non-CV s'il est renseigné.
Les dossiers sont **créés automatiquement** s'ils n'existent pas.

- **Rien n'est supprimé** : les mails changent seulement de dossier.
- **Seuls les mails déjà analysés bougent.** Un message arrivé après la dernière
  synchronisation reste dans la boîte de réception jusqu'à ce qu'il soit traité.
- Un mail rangé n'est **pas** réanalysé ensuite : le suivi des emails traités est conservé
  indépendamment de leur emplacement.

Trois points à connaître pour le bouton manuel :

1. Il utilise les réglages **enregistrés** — cliquez d'abord sur **💾 Enregistrer** si vous
   venez de modifier les noms de dossiers.
2. Il est **refusé pendant une synchronisation** (message *« Un traitement est en cours —
   réessayez après sa fin. »*) : le cycle lit la même boîte au même moment.
3. Il fonctionne **même si l'option automatique est désactivée** — pratique pour ranger de
   temps en temps sans changer le comportement des cycles.

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

> **URL du serveur Ollama** — la bonne valeur dépend de l'emplacement d'Ollama :
> - App installée en local (`.exe`) : `http://localhost:11434`
> - Application en conteneur Docker, Ollama sur le même serveur : `http://host.docker.internal:11434`
> - Ollama sur une autre machine : `http://<IP_du_serveur>:11434`
>
> Si le test échoue avec « serveur injoignable », c'est presque toujours cette URL.
> Astuce : Ollama doit être lancé avec `OLLAMA_HOST=0.0.0.0` pour être joignable
> depuis un conteneur ou un autre poste (par défaut il n'écoute qu'en local).

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

**Des mails ont disparu de la boîte de réception.**
Si le **rangement des mails traités** est activé (§19), les messages analysés sont déplacés
vers les dossiers de rangement (par défaut **Traités**). **Rien n'est supprimé** : ouvrez ces
dossiers dans votre messagerie pour les retrouver. Les candidats déjà enregistrés ne sont pas
affectés, et les mails rangés ne seront pas réanalysés.

**J'ai cliqué sur « Ranger les mails traités » et rien n'a bougé.**
Quatre causes possibles : les mails concernés **n'ont pas encore été analysés** (lancez d'abord
une synchronisation) ; ils ont **déjà été rangés** lors d'un cycle précédent ; le **dossier des
non-CV est vide** dans les réglages, donc les mails écartés restent volontairement en place ;
ou vos modifications de réglages **n'ont pas été enregistrées** avant le clic.

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
serveur et la maintenance, se reporter au **Manuel de déploiement**.*
