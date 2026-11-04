"""Nettoyage et construction du dataset global FAO (un pays = une ligne).

Chaque règle de traitement répond à une anomalie relevée dans le diagnostic (notebook J1) :

1. ``Valeur = "<0.1"`` dans la sous-alimentation (115 lignes) : ce n'est pas une donnée
   manquante, c'est « moins de 100 000 personnes ». Pour un petit pays (Dominique : 72 000
   habitants), cette borne ne dit rien du taux : on ne fixe donc pas de valeur, on garde
   une borne haute ``Taux_max_pct`` (0,1 million / population) qui encadre l'imputation.
   Les valeurs vides sont distinguées selon le symbole FAO : NR (non rapportée) et
   NV (non disponible).
2. Agrégat « Chine » (code 351) : il additionne Chine continentale, Taïwan, Hong-Kong et Macao,
   déjà présents séparément. On l'exclut pour ne pas compter 1,4 milliard de personnes deux fois.
3. Période : les bilans alimentaires et la population datent de 2013. On retient la période
   de sous-alimentation centrée sur 2013 (2012-2014). Paramétrable.
4. Valeurs négatives : surtout des « Variation de stock » (déstockage), légitimes : conservées.
   Seule exception utilisée ici : l'avoine au Japon a une disponibilité négative (-21 kcal,
   -0,37 g de protéines), physiquement impossible : exclue des sommes (``NEGATIFS_EXCLUS``).
5. Jointure : on part du socle des 175 zones ayant un bilan alimentaire et une population
   (jointure à gauche) ; les 29 zones suivies pour la sous-alimentation sans bilan alimentaire
   sont listées, pas perdues en silence.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

KCAL = "Disponibilité alimentaire (Kcal/personne/jour)"
PROT = "Disponibilité de protéines en quantité (g/personne/jour)"
CODE_CHINE_AGREGAT = 351
PERIODE_DEFAUT = "2012-2014"
BORNE_MILLIONS = 0.1  # "<0.1" = moins de 0,1 million de personnes


def charger(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """Charge les 5 fichiers FAO bruts."""
    noms = ["vegetaux", "animaux", "cereales", "population", "sousalimentation"]
    return {n: pd.read_csv(data_dir / f"fr_{n}.csv") for n in noms}


def _somme_element(df: pd.DataFrame, element: str, nom: str, produits: set[str] | None = None) -> pd.DataFrame:
    """Somme, par zone, de la valeur d'un élément (optionnellement restreint à certains produits).

    Une disponibilité alimentaire négative est impossible : ces valeurs sont exclues de la somme.
    """
    sous = df[(df["Élément"] == element) & (df["Valeur"] >= 0)]
    if produits is not None:
        sous = sous[sous["Produit"].isin(produits)]
    return sous.groupby("Code zone", as_index=False)["Valeur"].sum().rename(columns={"Valeur": nom})


def indicateurs_alimentaires(veg: pd.DataFrame, anim: pd.DataFrame, cer: pd.DataFrame) -> pd.DataFrame:
    """Kcal et protéines par personne et par jour, végétal / animal, et part des céréales."""
    cereales = set(cer["Produit"].unique())
    parts = [
        _somme_element(veg, KCAL, "Kcal_veg"),
        _somme_element(anim, KCAL, "Kcal_anim"),
        _somme_element(veg, KCAL, "Kcal_cereales", cereales),
        _somme_element(veg, PROT, "Prot_veg_g"),
        _somme_element(anim, PROT, "Prot_anim_g"),
    ]
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="Code zone", how="outer")
    out = out.fillna(0)
    out["Kcal_total"] = out["Kcal_veg"] + out["Kcal_anim"]
    out["Prot_total_g"] = out["Prot_veg_g"] + out["Prot_anim_g"]
    out["Part_kcal_animal_pct"] = out["Kcal_anim"] / out["Kcal_total"] * 100
    out["Part_kcal_cereales_pct"] = out["Kcal_cereales"] / out["Kcal_total"] * 100
    out["Part_prot_animal_pct"] = out["Prot_anim_g"] / out["Prot_total_g"] * 100
    return out


def population(pop: pd.DataFrame) -> pd.DataFrame:
    """Population 2013 en millions (le fichier est en milliers de personnes)."""
    out = pop[["Code zone", "Zone", "Valeur"]].rename(columns={"Valeur": "Population_milliers"})
    out["Population_millions"] = out["Population_milliers"] / 1000
    return out


def sous_alimentation(sous: pd.DataFrame, periode: str = PERIODE_DEFAUT) -> pd.DataFrame:
    """Nombre de personnes sous-alimentées (millions) pour une période, avec traitement de "<0.1"."""
    s = sous[sous["Année"].astype(str) == periode][["Code zone", "Valeur", "Symbole"]].copy()
    s["Sous_alim_borne"] = s["Valeur"].astype(str).str.strip() == "<0.1"
    s["Sous_alimentation_millions"] = pd.to_numeric(s["Valeur"], errors="coerce")
    return s.drop(columns="Valeur").rename(columns={"Symbole": "Symbole_sous_alim"})


def construire(sources: dict[str, pd.DataFrame], periode: str = PERIODE_DEFAUT,
               ref_regions: Path | None = DATA_DIR / "ref_zones_regions.csv") -> tuple[pd.DataFrame, dict]:
    """Construit le dataset global et un journal des décisions (zones exclues, comptages)."""
    pop = population(sources["population"])
    alim = indicateurs_alimentaires(sources["vegetaux"], sources["animaux"], sources["cereales"])
    sa = sous_alimentation(sources["sousalimentation"], periode)

    socle = pop.merge(alim, on="Code zone", how="left", validate="one_to_one")
    df = socle.merge(sa, on="Code zone", how="left", validate="one_to_one", indicator=True)

    journal = {
        "periode_sous_alimentation": periode,
        "zones_socle": len(socle),
        "zones_sans_bilan_alimentaire": sorted(
            sources["sousalimentation"].loc[~sources["sousalimentation"]["Code zone"].isin(pop["Code zone"]), "Zone"].unique()
        ),
        "agregat_exclu": "Chine (code 351) : somme de Chine continentale, Taïwan, Hong-Kong et Macao",
    }

    df = df[df["Code zone"] != CODE_CHINE_AGREGAT].drop(columns="_merge")
    df["Sous_alim_borne"] = df["Sous_alim_borne"].fillna(False).astype(bool)
    df["Taux_sous_nutrition_pct"] = df["Sous_alimentation_millions"] / df["Population_millions"] * 100
    df["Taux_max_pct"] = (BORNE_MILLIONS / df["Population_millions"] * 100).clip(upper=100).where(df["Sous_alim_borne"])
    df["Statut_sous_nutrition"] = "mesurée"
    df.loc[df["Sous_alim_borne"], "Statut_sous_nutrition"] = "< 0,1 million (borne)"
    df.loc[~df["Sous_alim_borne"] & df["Sous_alimentation_millions"].isna(), "Statut_sous_nutrition"] = (
        df["Symbole_sous_alim"].map({"NR": "non rapportée (NR)", "NV": "non disponible (NV)"}).fillna("absente")
    )

    if ref_regions is not None and Path(ref_regions).exists():
        ref = pd.read_csv(ref_regions)[["Code zone", "ISO3", "Region"]]
        df = df.merge(ref, on="Code zone", how="left", validate="one_to_one")

    journal["zones_finales"] = len(df)
    journal["statuts"] = df["Statut_sous_nutrition"].value_counts().to_dict()
    journal["zones_sans_valeur"] = sorted(df.loc[df["Taux_sous_nutrition_pct"].isna(), "Zone"])
    return df.reset_index(drop=True), journal


def exporter(df: pd.DataFrame, chemin: Path = DATA_DIR / "global_fao_dataset.csv") -> Path:
    """Écrit le dataset global en CSV (UTF-8)."""
    df.to_csv(chemin, index=False)
    return chemin


if __name__ == "__main__":
    data, log = construire(charger())
    print(f"Dataset global : {exporter(data)} ({len(data)} zones)")
    for k, v in log.items():
        print(f"- {k} : {v}")
