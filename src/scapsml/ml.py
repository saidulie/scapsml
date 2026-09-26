"""
ml -- supervised learning on a collected dataset.

    scapsml ml project.xlsx [--target PCE] [--kfold 10]

Follows the workflow of device-ML studies such as the MASnI3-xBrx work
(ACS Appl. Mater. Interfaces 2022, 14, 502): compare several algorithms,
interpret the best with SHAP, and use it for inverse design. Three things are
done more carefully than that template:

  FEATURES are discovered from the dataset, not listed, so any stack works.
  Resolved physical values (Eg, chi, eps) are used; the sampling columns that
  produced them (Eg_offset, eps_factor) are not, since value = interpolation +
  offset makes the three linearly dependent. Remaining exact dependencies --
  Nc, Nv and mobilities are usually functions of composition alone -- are
  pruned by correlation.

  VALIDATION uses three schemes, because on a structured grid a random split
  is optimistic: a held-out row usually sits between two training rows.
  Grouping by composition asks about an unseen composition; blocking asks
  about an unseen REGION. Quote those.

  SHAP runs twice -- all features, then the non-correlated subset. A feature
  whose importance collapses between passes was borrowing signal from a
  correlated partner.
"""

from __future__ import annotations

import csv
import json
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ._io import read_json, read_rows, write_json


@contextmanager
def _third_party_quiet():
    """
    Silence deprecation noise raised INSIDE third-party plotting code, and
    nothing else.

    SHAP's summary_plot calls matplotlib's Colormap.set_bad, which recent
    matplotlib marks as pending deprecation. That is about SHAP's internals,
    not anything a scapsml user did, and under a strict warnings policy it
    fails the run -- it passed on an older matplotlib and failed in a fresh
    install. Filtered here, locally, by category and message.

    A previous version called warnings.filterwarnings("ignore") at import
    time, silencing EVERY warning, process-wide, for anyone who imported the
    package -- including warnings about their own code. A library must not.
    """
    with warnings.catch_warnings():
        for cat in (DeprecationWarning, PendingDeprecationWarning, FutureWarning):
            warnings.filterwarnings("ignore", category=cat,
                                    module=r"(shap|matplotlib)(\.|$)")
        try:
            from matplotlib import MatplotlibDeprecationWarning
            warnings.filterwarnings("ignore", category=MatplotlibDeprecationWarning)
        except ImportError:
            pass
        warnings.filterwarnings("ignore", message=r".*set_bad.*")
        yield


@contextmanager
def _fit_quiet():
    """An MLP that stops at its iteration cap shows up in the scores, not as a
    wall of ConvergenceWarnings."""
    with warnings.catch_warnings():
        try:
            from sklearn.exceptions import ConvergenceWarning
            warnings.filterwarnings("ignore", category=ConvergenceWarning)
        except ImportError:
            pass
        yield

__all__ = ["run", "select_features", "model_zoo"]

TARGETS = ("PCE", "Voc", "Jsc", "FF")
UNITS = {"PCE": "%", "Voc": "V", "Jsc": "mA/cm2", "FF": "-"}
NOT_FEATURES = {"iv_file", "def_file", "abs_file", "status", "n_points",
                "source", "note", *TARGETS}
LOG_HINT = ("NA", "ND", "Nt", "Nc", "Nv", "Rsh", "Krad")


def _num(x):
    if x in ("", None):
        return np.nan
    if str(x).strip().lower() in ("inf", "+inf"):
        return np.inf
    try:
        return float(x)
    except ValueError:
        return np.nan


def _is_log(c):
    return any(c.startswith(h) for h in LOG_HINT)


def matrix(rows, cols):
    X = np.empty((len(rows), len(cols)))
    for j, c in enumerate(cols):
        v = np.array([_num(r[c]) for r in rows], float)
        if _is_log(c):
            ok = np.isfinite(v) & (v > 0)
            v = np.where(ok, np.log10(np.where(ok, v, 1.0)), np.nan)
            if np.isnan(v).any():
                fill = np.nanmax(v) + 1 if np.isfinite(v).any() else 0.0
                v = np.where(np.isnan(v), fill, v)
        X[:, j] = v
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


def select_features(rows, corr_threshold=0.98):
    """(all_features, non_correlated, dropped{name: reason})."""
    dropped, cols = {}, []
    for c in rows[0]:
        if c in NOT_FEATURES:
            continue
        if c.endswith(("_offset", "_factor")):
            dropped[c] = "sampling column; the resolved value is used instead"
            continue
        vals = {r[c] for r in rows}
        if len(vals) < 2:
            dropped[c] = "constant"
            continue
        if not np.isfinite([_num(v) for v in vals]).any():
            dropped[c] = "not numeric"
            continue
        cols.append(c)
    X = matrix(rows, cols)
    keep = []
    for j, c in enumerate(cols):
        hit = None
        for k in keep:
            a, b = X[:, j], X[:, cols.index(k)]
            if a.std() and b.std():
                r = abs(np.corrcoef(a, b)[0, 1])
                if r >= corr_threshold:
                    hit = (k, r)
                    break
        if hit:
            dropped[c] = f"|r| = {hit[1]:.4f} with {hit[0]}"
        else:
            keep.append(c)
    return cols, keep, dropped


def model_zoo(seed=0):
    from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                                  RandomForestRegressor)
    from sklearn.linear_model import RidgeCV
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVR
    from sklearn.tree import DecisionTreeRegressor
    z = {
        "linear regression": lambda: make_pipeline(
            StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13))),
        "decision tree": lambda: DecisionTreeRegressor(random_state=seed),
        "random forest": lambda: RandomForestRegressor(
            n_estimators=300, random_state=seed, n_jobs=-1),
        "extra trees": lambda: ExtraTreesRegressor(
            n_estimators=300, random_state=seed, n_jobs=-1),
        "gradient boosting": lambda: GradientBoostingRegressor(
            n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.9,
            random_state=seed),
        "SVR": lambda: make_pipeline(StandardScaler(),
                                     SVR(C=100.0, gamma="scale", epsilon=0.05)),
        "MLP": lambda: make_pipeline(StandardScaler(), MLPRegressor(
            hidden_layer_sizes=(128, 64), max_iter=1500, early_stopping=True,
            random_state=seed)),
    }
    try:
        from xgboost import XGBRegressor
        z["XGBoost"] = lambda: XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.05, subsample=0.9,
            colsample_bytree=0.9, random_state=seed, n_jobs=-1, verbosity=0)
    except ImportError:
        pass
    return z


def _shap(model, X, cols, outdir, tag, target, max_rows=4000):
    try:
        # SHAP calls matplotlib's Colormap.set_bad at IMPORT time
        # (shap/plots/colors/_colors.py), not only when plotting, so the
        # import itself must sit inside the scoped filter. In a long session
        # the module is usually cached by then and the warning never fires,
        # which is how this passed locally and failed in a clean install.
        with _third_party_quiet():
            import shap
    except ImportError:
        print("  SHAP skipped -- pip install scapsml[ml]")
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if len(X) > max_rows:
        X = X[np.random.default_rng(0).choice(len(X), max_rows, replace=False)]
    try:
        vals = np.asarray(shap.TreeExplainer(model).shap_values(
            X, check_additivity=False))
    except Exception:
        bg = shap.utils.sample(X, min(100, len(X)), random_state=0)
        vals = shap.Explainer(model.predict, bg, feature_names=cols)(X, silent=True).values
    h = 0.42 * len(cols) + 1.6
    with _third_party_quiet():
        for kind, name in (("dot", "summary"), ("bar", "bar")):
            plt.figure(figsize=(6.2, h))
            shap.summary_plot(vals, X, feature_names=cols, plot_type=kind,
                              show=False)
            plt.tight_layout()
            plt.savefig(outdir / f"shap_{tag}_{name}.png", dpi=200)
            plt.close()
    ma = np.abs(vals).mean(axis=0)
    print(f"  {'feature':<18} {'mean |SHAP|':>12}  direction at high values")
    for j in np.argsort(ma)[::-1]:
        hi = X[:, j] > np.median(X[:, j])
        d = vals[hi, j].mean() - vals[~hi, j].mean() if 0 < hi.sum() < len(hi) else 0
        print(f"  {cols[j]:<18} {ma[j]:>12.4f}  {'raises' if d > 0 else 'lowers'} "
              f"{target} by {abs(d):.3f}")
    return dict(zip(cols, ma.tolist()))


def run(dataset, outdir, target="PCE", kfold=10, candidates=20, verbose=True):
    from sklearn.ensemble import (GradientBoostingRegressor, RandomForestClassifier,
                                  RandomForestRegressor)
    from sklearn.metrics import mean_squared_error, r2_score
    from sklearn.model_selection import (GroupKFold, KFold, cross_val_predict,
                                         train_test_split)
    import joblib

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = list(read_rows(dataset))
    ok = [r for r in rows if r["status"] == "OK"]
    if len(ok) < 30:
        raise SystemExit(f"only {len(ok)} converged rows -- too few to model")
    rmse = lambda a, b: float(np.sqrt(mean_squared_error(a, b)))

    allf, keep, dropped = select_features(ok)
    print(f"dataset  : {len(rows)} rows, {len(ok)} converged "
          f"({100 * len(ok) / len(rows):.1f}%)")
    print(f"features : {', '.join(allf)}")
    print(f"           non-correlated: {', '.join(keep)}")
    for c, why in dropped.items():
        print(f"    dropped {c:<16} {why}")

    X = matrix(ok, allf)
    y = np.array([_num(r[target]) for r in ok])
    groups = np.array([_num(r.get("composition", 0)) for r in ok])
    ng = len(set(groups.tolist()))
    kf = KFold(max(2, min(kfold, len(ok) // 5)), shuffle=True, random_state=0)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=0)

    print(f"\n--- model comparison ({target}) ---")
    print(f"  {'model':<20} {'R2 train':>9} {'R2 test':>9} {'RMSE':>9} {'R2 kfold':>9}")
    table = {}
    zoo = model_zoo()
    with _fit_quiet():
        for name, make in zoo.items():
            m = make().fit(Xtr, ytr)
            pcv = cross_val_predict(make(), X, y, cv=kf)
            table[name] = {"r2_train": float(r2_score(ytr, m.predict(Xtr))),
                           "r2_test": float(r2_score(yte, m.predict(Xte))),
                           "rmse_test": rmse(yte, m.predict(Xte)),
                           "r2_kfold": float(r2_score(y, pcv))}
            t = table[name]
            print(f"  {name:<20} {t['r2_train']:>9.4f} {t['r2_test']:>9.4f} "
                  f"{t['rmse_test']:>9.4f} {t['r2_kfold']:>9.4f}")
    best = max(table, key=lambda k: table[k]["r2_kfold"])
    make = zoo[best]
    print(f"\n  best: {best}")

    gen = {}
    print(f"\n--- generalisation ({best}) ---")
    if ng >= 3:
        pg = cross_val_predict(make(), X, y, cv=GroupKFold(min(5, ng)), groups=groups)
        gen["grouped"] = float(r2_score(y, pg))
        print(f"  grouped by composition   R2 = {gen['grouped']:.4f}")
    uniq = np.array(sorted(set(groups.tolist())))
    if len(uniq) >= 8:
        r2s = []
        for blk in np.array_split(uniq, 4):
            te = np.isin(groups, blk)
            if 0 < te.sum() < len(te):
                r2s.append(r2_score(y[te], make().fit(X[~te], y[~te]).predict(X[te])))
        gen["blocked"] = float(np.mean(r2s))
        print(f"  blocked composition      R2 = {gen['blocked']:.4f}")
        if gen["blocked"] < 0.5:
            print("  The model interpolates between sampled compositions but does")
            print("  not extrapolate to unsampled regions. Frame it as an")
            print("  interpretation tool (SHAP), not a predictive surrogate.")

    print(f"\n--- SHAP, all {len(allf)} features ---")
    rf = RandomForestRegressor(n_estimators=300, random_state=0, n_jobs=-1).fit(X, y)
    s_all = _shap(rf, X, allf, outdir, "all", target)
    s_keep = None
    if len(keep) < len(allf):
        Xk = matrix(ok, keep)
        print(f"\n--- SHAP, {len(keep)} non-correlated features ---")
        s_keep = _shap(RandomForestRegressor(n_estimators=300, random_state=0,
                                             n_jobs=-1).fit(Xk, y),
                       Xk, keep, outdir, "nocorr", target)

    final = make().fit(X, y)
    joblib.dump({"model": final, "features": allf}, outdir / f"model_{target}.joblib")

    lo = GradientBoostingRegressor(loss="quantile", alpha=0.05, n_estimators=300,
                                   max_depth=4, random_state=0).fit(X, y)
    hi = GradientBoostingRegressor(loss="quantile", alpha=0.95, n_estimators=300,
                                   max_depth=4, random_state=0).fit(X, y)
    Xa = matrix(rows, allf)
    ya = np.array([r["status"] == "OK" for r in rows], int)
    clf = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1).fit(Xa, ya) \
        if 0 < ya.mean() < 1 else None
    rng = np.random.default_rng(1)
    cand = np.column_stack([rng.uniform(X[:, j].min(), X[:, j].max(), 100_000)
                            for j in range(X.shape[1])])
    if clf is not None:
        cand = cand[clf.predict_proba(cand)[:, 1] > 0.5]
    pred = final.predict(cand)
    top = np.argsort(pred)[::-1][:candidates]
    with open(outdir / "candidates.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank"] + allf + [f"{target}_pred", f"{target}_lo", f"{target}_hi"])
        plo, phi = lo.predict(cand[top]), hi.predict(cand[top])
        for k, i in enumerate(top):
            v = [10 ** x if _is_log(c) else x for x, c in zip(cand[i], allf)]
            w.writerow([k + 1] + [f"{x:.4g}" for x in v]
                       + [f"{pred[i]:.3f}", f"{plo[k]:.3f}", f"{phi[k]:.3f}"])
    bm = max(ok, key=lambda r: _num(r[target]))
    print(f"\n--- inverse design ---")
    print(f"  best predicted {target} {pred[top[0]]:.3f}  "
          f"[{plo[0]:.3f}, {phi[0]:.3f}] 90% interval")
    if not plo[0] <= pred[top[0]] <= phi[0]:
        print("  the point estimate lies OUTSIDE its own interval -- the optimiser")
        print("  has left the sampled region. Quote the best MEASURED cell instead.")
    print(f"  best measured  {target} {_num(bm[target]):.3f}")

    write_json(outdir / "metrics.json", {"best_model": best, "models": table, "generalisation": gen,
               "features": allf, "non_correlated": keep, "dropped": dropped,
               "shap_all": s_all, "shap_nocorr": s_keep})
    print(f"\nwrote {outdir}")
    return table
