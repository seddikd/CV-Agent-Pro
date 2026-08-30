# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Utilisateur principal :** un membre de l'équipe RH / recrutement qui reçoit des
candidatures spontanées et des réponses à des offres sur une boîte mail dédiée, et
qui doit les trier, retrouver un profil, et suivre où en est chaque candidat — sans
lire chaque pièce jointe à la main.

Quatre rôles applicatifs, définis dans `web_auth.py` :

| Rôle | Droits |
|---|---|
| `admin` | tout, y compris administration (paramètres, utilisateurs, RGPD, import) |
| `manager` | écriture + déclenchement d'un cycle de relève |
| `rh` | écriture (candidats, offres, notes, entretiens) |
| `lecture` | consultation seule |

**Situation de déploiement :** aujourd'hui une seule équipe RH connue ; le produit est
construit pour être déployé ensuite chez des entreprises clientes (une installation
Docker par client). Le design ne doit donc coder en dur ni le vocabulaire, ni les
volumes, ni l'organigramme d'une seule société.

## Product Purpose

Automatiser le haut de l'entonnoir de recrutement : relever une boîte IMAP, détecter
par LLM lesquels des messages portent un CV, en extraire les données structurées,
stocker les candidats en PostgreSQL, et servir un ATS web francophone à l'équipe RH.

```
[IMAP] → [PDF/DOCX → texte] → [LLM : est-ce un CV ?] → [LLM : extraction] → [PostgreSQL] → [ATS web]
```

Le succès : un CV reçu devient une fiche candidat exploitable et retrouvable sans
intervention humaine, et l'équipe RH travaille dans l'interface plutôt que dans la
boîte mail.

## Positioning

- **Traitement 100 % local.** Aucune donnée candidat ne quitte le réseau, sauf si le
  fournisseur LLM cloud (`openrouter`) est explicitement choisi dans les réglages.
  C'est la promesse centrale sur des données RH nominatives.
- **Le matching offre ↔ candidat est déterministe et hors-ligne** (`matching_core.py`),
  pas un appel LLM : le même couple donne toujours le même score, donc un score se
  défend devant un candidat ou un manager.
- **Toute boîte IMAP**, pas seulement Gmail : `imap.security` couvre SSL / STARTTLS /
  None, ce qui inclut les serveurs internes et les hébergeurs locaux.
- **Relève en lecture seule par défaut.** Les mails ne sont même pas marqués « lus » ;
  le rangement des traités est une option explicite.

## Operating Context

- **Déploiement Docker uniquement.** Un seul worker uvicorn (APScheduler et l'écriture
  base supposent un process unique).
- **Cycle automatique toutes les 60 min**, ou déclenché à la main par un `admin` /
  `manager`.
- **Configuration au runtime en base** (table `settings`), éditée depuis l'interface
  d'administration ; `config.yaml` n'est qu'un gabarit de premier lancement.
  `CV_AGENT_DB_URL` est la seule variable obligatoire.
- **Une boîte mail dédiée aux candidatures** est un prérequis d'installation ; selon le
  fournisseur, un mot de passe d'application peut être nécessaire.
- **Voie d'entrée secondaire :** import ponctuel d'archives Outlook `.pst` / `.ost`
  (page *Import Outlook*), avec son propre rangement des traités, rapproché par
  Message-ID et non par UID.
- **Langue de l'interface : français**, y compris les libellés de statut et les
  intitulés de rôle.

## Capabilities and Constraints

**Modules ATS livrés** (un routeur `mod_*.py` par module, montés sur `web_core`) :
tableau de bord, statistiques, recherche classique, recherche IA en langage naturel,
offres d'emploi, matching IA, alertes, doublons, notes internes, fiche de synthèse IA,
gestion documentaire, comparaison de 2 à 5 candidats, timeline candidat, emails,
entretiens et rappels, reporting, RGPD, export Excel, API REST, pipeline, import.

**Contraintes techniques confirmées :**

- PostgreSQL est l'unique moteur de base et la source de vérité.
- Fournisseur LLM au choix, **sans bascule automatique** : Ollama local
  (ex. `qwen2.5:14b`) ou point d'accès compatible OpenAI (OpenRouter, Gemini…).
- Secrets chiffrés au repos (`enc:v2:`, Fernet, clé dérivée de `CV_AGENT_SECRET`) ;
  un blob indéchiffrable rend `""`, jamais un crash.
- Front : FastAPI + Jinja + HTMX, `static/htmx.min.js` servi localement. Pas de build
  front, pas de bundler, pas de framework SPA.
- Référentiel géographique algérien embarqué (`algeria_geo.py`) pour la normalisation
  des localisations candidat.

**Non décidé :** le modèle de commercialisation (licence, prix, packaging) n'est pas
arrêté — aucun travail futur ne doit l'inventer.

## Brand Commitments

- **Rayanox est une identité contraignante**, confirmée par le client : le nom, le
  logo (`Presentation/logo-01.jpg`) et la palette de marque sont préservés. Une refonte
  visuelle future ne remplace pas cette palette.
- La palette vit dans `static/style.css` sous forme de variables CSS, avec les ratios
  de contraste WCAG mesurés en commentaire : `#233873` 10,91:1 · `#295894` 7,05:1 ·
  `#1E8DCC` 3,59:1 · `#5998C6` 3,06:1 · `#B2C9E2` 1,67:1 sur fond clair. Les rôles
  (`--primary`, `--accent`, `--primary-soft`…) ont été attribués d'après ces mesures,
  pas au jugé — c'est un travail à conserver, pas à refaire.
- Thème clair **et** sombre, la palette sombre inversant l'échelle de marque.
- Voix : français professionnel, vouvoiement, vocabulaire RH métier.

## Evidence on Hand

- `MANUEL_UTILISATION.pdf` et `MANUEL_DEPLOIEMENT.pdf` (manuels livrés, générés par
  `build_pdf.py`).
- `Presentation/` : support commercial en `.pptx`, `.pdf`, `.html`, un guide de
  présentation, le logo, et un dossier `captures` de copies d'écran réelles.
- `README.md` : description fonctionnelle et architecturale à jour.
- **Absences à ne jamais combler par invention :** aucun témoignage client, aucune
  étude de cas, aucun chiffre de performance publié, aucun tarif, aucune référence
  presse. Il n'existe pas non plus de `CLAUDE.md` à la racine, bien que le README y
  renvoie.

## Product Principles

1. **La donnée candidat ne sort pas du réseau sans un choix explicite.** Toute
   fonctionnalité future se conçoit d'abord en mode local.
2. **Un score ou un rapprochement doit être explicable.** Le déterminisme du matching
   est un engagement produit, pas un détail d'implémentation.
3. **La boîte mail reste intacte tant que personne n'a demandé le contraire.** Les
   actions destructrices ou irréversibles sur l'IMAP sont opt-in.
4. **L'administration se fait dans l'interface, pas dans un fichier.** La configuration
   au runtime vit en base et s'édite par un écran.
5. **Le produit s'installe chez un client sans être réécrit.** Pas d'hypothèse codée en
   dur sur une seule entreprise.

## Accessibility & Inclusion

Pas de standard contractuel établi. L'accessibilité est traitée comme un niveau de
craft : les contrastes de la palette sont mesurés et documentés, et le thème sombre
respecte les mêmes seuils. À maintenir à ce niveau ; à ne pas présenter comme une
conformité certifiée.
