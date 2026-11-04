"""Tests du pipeline et du profiler : lancer `pytest` depuis la racine du projet."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import fao_pipeline as fp  # noqa: E402
from profiler import DataProfiler, ProfileurFAO  # noqa: E402


@pytest.fixture(scope="module")
def resultat():
    return fp.construire(fp.charger())


def test_une_ligne_par_zone(resultat):
    df, _ = resultat
    assert df["Code zone"].is_unique
    assert len(df) == 174


def test_agregat_chine_exclu(resultat):
    df, _ = resultat
    assert fp.CODE_CHINE_AGREGAT not in set(df["Code zone"])
    assert "Chine, continentale" in set(df["Zone"])


def test_borne_inf_0_1_non_convertie_en_zero(resultat):
    df, _ = resultat
    bornes = df[df["Sous_alim_borne"]]
    assert len(bornes) > 0
    assert bornes["Taux_sous_nutrition_pct"].isna().all()
    assert (bornes["Taux_max_pct"] > 0).all()


def test_kcal_total_coherent(resultat):
    df, _ = resultat
    assert (df["Kcal_total"] - df["Kcal_veg"] - df["Kcal_anim"]).abs().max() < 1e-9
    assert df["Kcal_total"].between(1500, 4000).all()


def test_taux_dans_0_100(resultat):
    df, _ = resultat
    assert df["Taux_sous_nutrition_pct"].dropna().between(0, 100).all()


def test_zones_sans_bilan_listees(resultat):
    _, journal = resultat
    assert len(journal["zones_sans_bilan_alimentaire"]) == 29


def test_profiler_generique():
    df = pd.DataFrame({"a": [1, 1, None], "b": ["x", "x", "y"]})
    p = DataProfiler(df, "test")
    assert p.doublons_complets() == 1
    assert p.taux_nan().loc["a", "nb_nan"] == 1


def test_profileur_fao_detecte_inf_0_1():
    s = fp.charger()["sousalimentation"]
    vt = ProfileurFAO(s, "sous-alimentation").valeurs_non_numeriques()
    assert vt.get("<0.1", 0) == 115
