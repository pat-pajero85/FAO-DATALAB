"""Diagnostic qualité des fichiers FAO.

Deux classes :
- ``DataProfiler`` : diagnostic générique, utilisable sur n'importe quel DataFrame ;
- ``ProfileurFAO`` : spécialisation pour les fichiers FAO (format long : une ligne
  par zone x produit x élément x année).

Aucune méthode ne modifie le DataFrame d'origine : le profiler observe, il ne nettoie pas.
"""

from __future__ import annotations

import pandas as pd


class DataProfiler:
    """Diagnostic qualité générique d'un DataFrame.

    Args:
        df: données à diagnostiquer.
        nom_source: nom affiché dans les rapports (ex. nom du fichier).
    """

    def __init__(self, df: pd.DataFrame, nom_source: str) -> None:
        self.df = df
        self.nom_source = nom_source

    def taux_nan(self) -> pd.DataFrame:
        """Nombre et pourcentage de valeurs manquantes par colonne (colonnes concernées seulement)."""
        n = self.df.isna().sum()
        out = pd.DataFrame({"nb_nan": n, "pct_nan": (n / len(self.df) * 100).round(2)})
        return out[out["nb_nan"] > 0].sort_values("nb_nan", ascending=False)

    def doublons_complets(self) -> int:
        """Nombre de lignes strictement identiques à une ligne précédente."""
        return int(self.df.duplicated().sum())

    def doublons_cle(self, cle: list[str]) -> int:
        """Nombre de lignes qui répètent une combinaison de colonnes censée être unique."""
        return int(self.df.duplicated(subset=cle).sum())

    def resume(self) -> dict:
        """Synthèse en une ligne : taille, NaN, doublons."""
        return {
            "source": self.nom_source,
            "lignes": len(self.df),
            "colonnes": self.df.shape[1],
            "cellules_nan": int(self.df.isna().sum().sum()),
            "doublons_complets": self.doublons_complets(),
        }


class ProfileurFAO(DataProfiler):
    """Diagnostic spécialisé pour les fichiers FAO (bilans alimentaires, population, sous-alimentation)."""

    CLE_ZONE = "Code zone"
    CLE_METIER = ["Code zone", "Code Produit", "Code Élément", "Code année"]

    def valeurs_non_numeriques(self) -> pd.Series:
        """Valeurs de la colonne ``Valeur`` qui ne sont pas des nombres (ex. ``"<0.1"``), avec leur effectif."""
        brut = self.df["Valeur"]
        num = pd.to_numeric(brut, errors="coerce")
        return brut[num.isna() & brut.notna()].value_counts()

    def doublons_metier(self) -> int:
        """Doublons sur la clé zone x produit x élément x année."""
        return self.doublons_cle(self.CLE_METIER)

    def unites_par_element(self) -> pd.DataFrame:
        """Unités utilisées pour chaque élément : plus d'une unité par élément serait une anomalie."""
        return self.df.groupby("Élément")["Unité"].unique().apply(list).to_frame("unites")

    def valeurs_negatives(self) -> pd.Series:
        """Nombre de valeurs négatives par élément (une variation de stock négative est normale)."""
        num = pd.to_numeric(self.df["Valeur"], errors="coerce")
        neg = self.df.loc[num < 0, "Élément"]
        return neg.value_counts()

    def periodes(self) -> list[str]:
        """Périodes (colonne ``Année``) présentes dans le fichier."""
        return sorted(self.df["Année"].astype(str).unique())

    def zones(self) -> set[int]:
        """Codes zone présents dans le fichier."""
        return set(self.df[self.CLE_ZONE].unique())

    def ecart_couverture(self, autre: "ProfileurFAO") -> dict[str, list[str]]:
        """Zones présentes dans un fichier et absentes de l'autre (dans les deux sens), par nom."""
        noms = pd.concat([self.df, autre.df])[[self.CLE_ZONE, "Zone"]].drop_duplicates(self.CLE_ZONE)
        noms = noms.set_index(self.CLE_ZONE)["Zone"]
        seul_ici = sorted(noms[list(self.zones() - autre.zones())])
        seul_la = sorted(noms[list(autre.zones() - self.zones())])
        return {f"seulement dans {self.nom_source}": seul_ici, f"seulement dans {autre.nom_source}": seul_la}

    def valeurs_extremes(self, element: str, seuil_iqr: float = 3.0) -> pd.DataFrame:
        """Valeurs au-delà de Q3 + seuil x IQR (ou en deçà de Q1 - seuil x IQR) pour un élément donné."""
        sous = self.df[self.df["Élément"] == element].copy()
        sous["Valeur_num"] = pd.to_numeric(sous["Valeur"], errors="coerce")
        q1, q3 = sous["Valeur_num"].quantile([0.25, 0.75])
        iqr = q3 - q1
        masque = (sous["Valeur_num"] > q3 + seuil_iqr * iqr) | (sous["Valeur_num"] < q1 - seuil_iqr * iqr)
        return sous.loc[masque, ["Zone", "Produit", "Valeur_num", "Unité"]].sort_values("Valeur_num", ascending=False)

    def rapport(self) -> dict:
        """Synthèse chiffrée des 4 familles d'anomalies pour ce fichier."""
        base = self.resume()
        base.update({
            "zones": len(self.zones()),
            "periodes": ", ".join(self.periodes()),
            "valeur_nan": int(pd.to_numeric(self.df["Valeur"], errors="coerce").isna().sum()),
            "valeur_texte": int(self.valeurs_non_numeriques().sum()),
            "doublons_metier": self.doublons_metier(),
            "valeurs_negatives": int(self.valeurs_negatives().sum()),
            "unites_multiples": int((self.unites_par_element()["unites"].str.len() > 1).sum()),
        })
        return base
