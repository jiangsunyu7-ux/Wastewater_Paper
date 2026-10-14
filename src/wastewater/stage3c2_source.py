"""Stage3C2 finite source pools using the unchanged Stage3B Ridge algebra.

Only source fitting (2016--2021) and the original source pseudo-deployments
(2021) occur here. No target deployment losses enter source selection. The
three-source local fallback is passed separately to target selection so that
expanding a shared pool cannot silently strengthen or weaken the local rule.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd
import sklearn

from .common import sha256, utc_now, write_json
from .shared_data import scale_from_history, train_samples
from .stage3a_data import compact
from .stage3b_experiment import array_hash, read_models, save_models
from .stage3b_models import (calibration_fold, candidate_scores,
    choose_parameters, estimate_bias, residual_target, ridge_fit, subset, usable)


ORIGINAL_SOURCES = ("13006", "13008", "13012")
REQUIRED_MODEL_GROUPS = ("final", "proxy") + tuple("loso_" + s for s in ORIGINAL_SOURCES)
_FEATURE_CACHE = {}
_LOCAL_GRID_CACHE = {}
_LOCAL_GRID_COUNTS = {"hits": 0, "misses": 0, "fits": 0}


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def linked_sites(site, related_ids=None):
    """Conservative undirected transitive closure of already-known links.

The input maps SiteID to a list of known or suspected related SiteIDs. No
name-derived independence is inferred here. Empty/unknown maps mean only
the site itself is identified, not that it is a verified physical facility.
"""
    result = {str(site)}
    adjacency = {}
    for key, members in (related_ids or {}).items():
        if isinstance(members, str):
            raise TypeError("related_ids must map SiteIDs to lists, not facility-name strings")
        group = {str(key), *(str(member) for member in members)}
        for member in group:
            adjacency.setdefault(member, set()).update(group)
    pending = list(result)
    while pending:
        member = pending.pop()
        for other in adjacency.get(member, ()):
            if other not in result:
                result.add(other)
                pending.append(other)
    return result


def validate_source_settings(cfg, source_ids, related_ids=None):
    if len(source_ids) != len(set(source_ids)) or not source_ids:
        raise ValueError("A source pool must contain unique SiteIDs")
    if not set(ORIGINAL_SOURCES).issubset(source_ids):
        raise ValueError("Each nested pool must include the original three sources")
    for site in source_ids:
        if (linked_sites(site, related_ids) - {site}) & set(source_ids):
            raise ValueError("A known/suspected related group contributes more than one source")
    expected = dict(source_training_start="2016-01-01", source_training_end="2021-12-31",
        source_selection_train_end="2020-12-31", source_pseudo_validation_days=14,
        source_pseudo_origins=["2021-01-01", "2021-07-01"], budgets=[30, 90, 180],
        horizons=[1, 3], ridge_alphas=[.0001, .001, .01, .1, 1., 10.], lambdas=[0, .25, .5, 1])
    for key, value in expected.items():
        if cfg.get(key) != value:
            raise ValueError(f"Stage3C2 source rule changed: {key}")


def _series_prefix_hash(series, start, end):
    prefix = series.loc[start:end]
    return _hash_json(dict(index=array_hash(prefix.index.to_numpy()),
                           values=array_hash(prefix.to_numpy(dtype=float))))


def _source_features(series, site, cfg, horizon, end):
    """Reuse legal per-SiteID features across all seven finite source pools."""
    start = cfg["source_training_start"]
    key = (site, start, end, int(horizon), _series_prefix_hash(series, start, end),
           int(cfg["min_train_labels"]))
    if key not in _FEATURE_CACHE:
        scale = scale_from_history(series, start, end)
        data = train_samples(series, start, end, horizon, scale)
        data = subset(data, usable(data))
        if len(data.y) < cfg["min_train_labels"]:
            raise ValueError(f"Insufficient legal source labels: {site}/{end}/H{horizon}")
        if data.targets.max() > pd.Timestamp(end):
            raise AssertionError("Source training label crosses the allowed end date")
        info = dict(site_id=site, training_labels=len(data.y), scale_m3=scale,
            normalization_fit_start=start, normalization_fit_end=end,
            first_train_origin=str(data.origins.min().date()), last_train_origin=str(data.origins.max().date()),
            first_train_target=str(data.targets.min().date()), last_train_target=str(data.targets.max().date()))
        _FEATURE_CACHE[key] = (compact(data.X), data.y, residual_target(data), info)
    return _FEATURE_CACHE[key]


def source_arrays(series, cfg, horizon, end, ids):
    """Exactly Stage3B source_pool weights: each source has total weight 1/K."""
    if not ids:
        raise ValueError("LOSO leaves no source training SiteIDs")
    xs, ys, rs, ws, diagnostics = [], [], [], [], []
    for site in ids:
        x, y, r, info = _source_features(series[site], site, cfg, horizon, end)
        weights = np.full(len(y), 1 / (len(ids) * len(y)))
        xs.append(x); ys.append(y); rs.append(r); ws.append(weights)
        diagnostics.append(dict(info, weight_sum=1 / len(ids),
            individual_sample_weight=1 / (len(ids) * len(y))))
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(rs), np.concatenate(ws), diagnostics


def source_candidate_scores(train, validation, shared_models, cfg):
    """Exactly Stage3B candidate_scores, with shared-independent local reuse.

Each legal fold's local alpha fits are identical across source pools. Their
cache uses only the fitting/validation feature and residual arrays and the
finite grid. Shared fits and local biases remain pool-specific. Return fresh
row dictionaries so the caller's fold metadata cannot mutate this cache.
"""
    train_x, val_x = compact(train.X), compact(validation.X)
    train_residual, val_residual = residual_target(train), residual_target(validation)
    key = _hash_json(dict(training_X=array_hash(train_x), training_r=array_hash(train_residual),
        validation_X=array_hash(val_x), validation_r=array_hash(val_residual),
        ridge_alphas=cfg["ridge_alphas"], lambdas=cfg["lambdas"],
        fitting_labels=len(train.y), validation_labels=len(validation.y)))
    if key not in _LOCAL_GRID_CACHE:
        local_rows = {}
        for alpha in cfg["ridge_alphas"]:
            model = ridge_fit(train_x, train_residual, alpha)
            predicted = model.predict(val_x) + 0.
            rows = []
            for lam in cfg["lambdas"]:
                error = float(lam) * predicted - val_residual
                rows.append(dict(family="local_residual_ridge", alpha=float(alpha), shrinkage=float(lam),
                    validation_mae=float(np.mean(np.abs(error))), validation_mse=float(np.mean(error ** 2)),
                    bias_normalized=0., fitting_labels=len(train.y), validation_labels=len(validation.y)))
            local_rows[float(alpha)] = rows
        _LOCAL_GRID_CACHE[key] = local_rows
        _LOCAL_GRID_COUNTS["misses"] += 1
        _LOCAL_GRID_COUNTS["fits"] += len(cfg["ridge_alphas"])
    else:
        _LOCAL_GRID_COUNTS["hits"] += 1
    rows = []
    for alpha in cfg["ridge_alphas"]:
        rows.extend(dict(row) for row in _LOCAL_GRID_CACHE[key][float(alpha)])
        shared = shared_models[float(alpha)]
        bias = estimate_bias(shared, train)
        for family, b in (("shared_residual_ridge", 0.), ("shared_residual_ridge_bias", bias)):
            predicted = shared.predict(val_x) + b
            for lam in cfg["lambdas"]:
                error = float(lam) * predicted - val_residual
                rows.append(dict(family=family, alpha=float(alpha), shrinkage=float(lam),
                    validation_mae=float(np.mean(np.abs(error))), validation_mse=float(np.mean(error ** 2)),
                    bias_normalized=b, fitting_labels=len(train.y), validation_labels=len(validation.y)))
    return rows


def _required_outputs(cfg):
    return {f"{name}_H{h}.npz" for name in REQUIRED_MODEL_GROUPS for h in cfg["horizons"]} | {
        "selection.json", "source_diagnostics.json", "pseudo_validation_folds.json", "residual_fallback_grid.csv"}


def validate_completed_source_cache(folder, fingerprint, cfg):
    """A partial cache never counts as complete, even when failed=0."""
    folder = Path(folder)
    path = folder / "status.json"
    if not path.is_file():
        return False
    status = json.loads(path.read_text())
    if status.get("fingerprint") != fingerprint:
        raise ValueError("Source cache fingerprint mismatch; use a new version")
    if status.get("status") != "completed":
        return False
    hashes = status.get("outputs_sha256", {})
    if not _required_outputs(cfg).issubset(hashes):
        raise ValueError("Completed source cache lacks required model/selection outputs")
    if status.get("completed_model_groups") != status.get("expected_model_groups") or status.get("completed_model_groups") != 10:
        raise ValueError("Source cache reports incomplete model groups")
    if status.get("completed_pseudo_folds") != status.get("expected_pseudo_folds") or status.get("completed_pseudo_folds") != 36:
        raise ValueError("Source cache reports incomplete pseudo-validation folds")
    for member, expected in hashes.items():
        if not (folder / member).is_file() or sha256(folder / member) != expected:
            raise ValueError(f"Source cached output missing/modified: {member}")
    return True


def load_source_bank(folder, cfg, fingerprint=None):
    """Load source models only after checking all completion/member checksums."""
    folder = Path(folder)
    state = json.loads((folder / "status.json").read_text())
    fingerprint = fingerprint or state.get("fingerprint")
    if not validate_completed_source_cache(folder, fingerprint, cfg):
        raise ValueError("Cannot load a partial/unexecuted/failed source bank")
    selection = json.loads((folder / "selection.json").read_text())
    final, proxy, loso = {}, {}, {s: {} for s in ORIGINAL_SOURCES}
    for horizon in cfg["horizons"]:
        final[horizon] = read_models(folder / f"final_H{horizon}.npz")[1]
        proxy[horizon] = read_models(folder / f"proxy_H{horizon}.npz")[1]
        for held in ORIGINAL_SOURCES:
            loso[held][horizon] = read_models(folder / f"loso_{held}_H{horizon}.npz")[1]
    return dict(pool_id=selection["pool_id"], source_ids=selection["source_ids"],
        final=final, proxy=proxy, loso=loso, source_selection=selection,
        cache_status=state, folder=str(folder))


def prepare_source_bank(cfg, series, source_ids, source_output, related_ids=None,
                        signature=None, pool_id="K3", related_groups=None, pool_key=None):
    """Prepare once per unique pool; return (loaded bank, fallback_settings).

Direct-volume coefficients are also saved to the unchanged Stage3B NPZ
schema for exact scientific-code checks, but Stage3C2 evaluates only the
registered residual policies. They are not extra candidate model families.
"""
    if related_groups is not None:
        if related_ids is not None:
            raise ValueError("Supply one related-site map")
        related_ids = related_groups
    if pool_key is not None:
        pool_id = pool_key
    ids = [str(s) for s in source_ids]
    validate_source_settings(cfg, ids, related_ids)
    folder = Path(source_output)
    folder.mkdir(parents=True, exist_ok=True)
    provenance = dict(pool_id=pool_id, source_ids=ids, related_ids=related_ids or {},
        run_signature=signature,
        legal_source_prefix_sha256={s: _series_prefix_hash(series[s], "2016-01-01", "2021-12-31") for s in ids},
        source_rule={key: cfg[key] for key in ("source_training_start", "source_training_end",
            "source_selection_train_end", "source_pseudo_origins", "source_pseudo_validation_days",
            "budgets", "horizons", "ridge_alphas", "lambdas", "min_train_labels",
            "local_validation_fraction", "validation_min_fit_labels", "validation_min_labels")},
        code_sha256={p.name: sha256(p) for p in (Path(__file__), Path(__file__).with_name("stage3b_models.py"),
            Path(__file__).with_name("stage3b_experiment.py"), Path(__file__).with_name("shared_data.py"),
            Path(__file__).with_name("stage3a_data.py"))},
        sklearn=sklearn.__version__, numpy=np.__version__, pandas=pd.__version__)
    fingerprint = _hash_json(provenance)
    if validate_completed_source_cache(folder, fingerprint, cfg):
        bank = load_source_bank(folder, cfg, fingerprint)
        bank["cache_reused"] = True
        return bank, bank["source_selection"]["fallback_settings"]
    status_file = folder / "status.json"
    previous = json.loads(status_file.read_text()) if status_file.exists() else {}
    # Failed attempts retain their traceback; partial member files are safely
    # regenerated with this exact same configuration rather than trusted.
    attempt = previous.get("attempt", 0) + 1
    state = dict(status="running", fingerprint=fingerprint, attempt=attempt,
        provenance=provenance, started_utc=utc_now(), expected_model_groups=10,
        completed_model_groups=0, expected_pseudo_folds=36, completed_pseudo_folds=0,
        physical_mapping_verified=False, device="cpu")
    write_json(status_file, state)
    start_time = time.perf_counter()
    local_cache_before = _LOCAL_GRID_COUNTS.copy()
    try:
        diagnostics = []
        groups = [("final", cfg["source_training_end"], ids),
                  ("proxy", cfg["source_selection_train_end"], ids)]
        for held in ORIGINAL_SOURCES:
            excluded = linked_sites(held, related_ids)
            groups.append((f"loso_{held}", "2020-12-31", [s for s in ids if s not in excluded]))
        for name, end, group_ids in groups:
            for horizon in cfg["horizons"]:
                x, y, residuals, weights, diag = source_arrays(series, cfg, horizon, end, group_ids)
                direct, residual = {}, {}
                for alpha in cfg["ridge_alphas"]:
                    direct[float(alpha)] = ridge_fit(x, y, alpha, weights)
                    residual[float(alpha)] = ridge_fit(x, residuals, alpha, weights)
                save_models(folder / f"{name}_H{horizon}.npz", direct, residual, cfg["ridge_alphas"])
                diagnostics.append(dict(group=name, horizon=horizon, source_ids=group_ids, fit_end=end, sites=diag,
                    total_training_labels=len(y), nominal_parameters=7, features=6,
                    weight_sum=float(weights.sum()), objective="sum(w*(y-Xb-intercept)^2)+alpha*sum(b^2)",
                    intercept_penalized=False, training_X_sha256=array_hash(x), label_sha256=array_hash(y),
                    residual_label_sha256=array_hash(residuals), weights_sha256=array_hash(weights)))
                state["completed_model_groups"] += 1
                state["last_progress_utc"] = utc_now()
                write_json(status_file, state)
                print(f"source {pool_id} {state['completed_model_groups']}/10 {name} H{horizon} labels={len(y)}", flush=True)
        all_scores, folds, fallback = [], [], {}
        for budget in cfg["budgets"]:
            for horizon in cfg["horizons"]:
                relevant = []
                for held in ORIGINAL_SOURCES:
                    source_residual = read_models(folder / f"loso_{held}_H{horizon}.npz")[1]
                    excluded = linked_sites(held, related_ids)
                    used_ids = [s for s in ids if s not in excluded]
                    for date in cfg["source_pseudo_origins"]:
                        train, val, diag = calibration_fold(series[held], date, budget, horizon, cfg, pseudo=True)
                        if not diag["valid"]:
                            raise ValueError(f"Invalid fixed source fallback fold {held}/{date}/B{budget}/H{horizon}")
                        if set(used_ids) & excluded or pd.Timestamp("2020-12-31") >= val.origins.min():
                            raise AssertionError("LOSO linked-SiteID/time isolation failed")
                        fold_id = f"{held}_{date}_B{budget}_H{horizon}"
                        folds.append(dict(diag, fold_id=fold_id, held_out_source=held,
                            excluded_linked_ids=sorted(excluded), shared_fit_sites=used_ids,
                            shared_fit_end="2020-12-31", pool_id=pool_id))
                        rows = source_candidate_scores(train, val, source_residual, cfg)
                        for row in rows:
                            row.update(fold_id=fold_id, held_out_source=held, budget=budget, horizon=horizon,
                                normalization_fit_end=diag["normalization_fit_end"], pool_id=pool_id)
                        relevant.extend(rows); all_scores.extend(rows)
                        state["completed_pseudo_folds"] += 1
                        state["last_progress_utc"] = utc_now()
                        write_json(status_file, state)
                fallback[f"B{budget}_H{horizon}"] = dict(parameters=choose_parameters(relevant),
                    source_assisted=True, folds=6, fitting_source_end="2020-12-31",
                    validation_end="2021-07-17" if horizon == 3 else "2021-07-15",
                    pool_id=pool_id, local_rule="always use independently frozen K3 local fallback")
                print(f"source validation {pool_id} {state['completed_pseudo_folds']}/36 B{budget} H{horizon}", flush=True)
        selection = dict(signature=signature, fingerprint=fingerprint, pool_id=pool_id, source_ids=ids,
            fallback_settings=fallback, tuning_loss="normalized MAE", training_loss="weighted MSE",
            hyperparameter_information="fixed original three source LOSO 2021 auxiliary validation; source fit<=2020",
            selection_uses_deployment_labels=False, physical_mapping_verified=False,
            source_model_diagnostics=diagnostics)
        write_json(folder / "selection.json", selection)
        write_json(folder / "pseudo_validation_folds.json", folds)
        pd.DataFrame(all_scores).to_csv(folder / "residual_fallback_grid.csv", index=False)
        write_json(folder / "source_diagnostics.json", diagnostics)
        if state["completed_model_groups"] != 10 or state["completed_pseudo_folds"] != 36:
            raise AssertionError("Source computation is partial")
        required = _required_outputs(cfg)
        if not all((folder / name).is_file() for name in required):
            raise AssertionError("A required source output is missing")
        state.update(status="completed", finished_utc=utc_now(), seconds=time.perf_counter()-start_time,
            outputs_sha256={name: sha256(folder / name) for name in sorted(required)},
            fitted_Ridge_count=120, evaluated_shared_candidate_grids=36,
            source_pseudo_local_validation_cache_this_pool={key: value-local_cache_before[key]
                for key, value in _LOCAL_GRID_COUNTS.items()},
            retained_failure_logs=sorted(p.name for p in folder.glob("failure_attempt_*.txt")))
        write_json(status_file, state)
    except Exception as error:
        failure = folder / f"failure_attempt_{attempt}.txt"
        failure.write_text(traceback.format_exc())
        state.update(status="failed", error=str(error), finished_utc=utc_now(), seconds=time.perf_counter()-start_time)
        write_json(status_file, state)
        raise
    bank = load_source_bank(folder, cfg, fingerprint)
    bank["cache_reused"] = False
    return bank, fallback


def select_residual_for_target(series, cfg, date, budget, horizon, bank, local_fallback):
    """Same legal Stage3B target fold, current-pool shared choices, K3 local rule."""
    train, val, fold = calibration_fold(series, date, budget, horizon, cfg)
    if fold["valid"]:
        if pd.Timestamp("2020-12-31") >= val.origins.min():
            raise AssertionError("Shared validation proxy includes future validation information")
        grid = candidate_scores(train, val, bank["proxy"][horizon], cfg)
        parameters = choose_parameters(grid)
        fold.update(shared_proxy_fit_end="2020-12-31", source_assisted=False,
                    choice_source="budget_internal_chronological_validation")
    else:
        key = f"B{budget}_H{horizon}"
        fallback = bank["source_selection"]["fallback_settings"][key]
        parameters = deepcopy(fallback["parameters"])
        # Deliberately preserve the matched local selection from K3, even when
        # the current pool produces a different shared source-validation rank.
        for name, decision in local_fallback[key]["parameters"].items():
            if name.startswith("local_"):
                parameters[name] = deepcopy(decision)
        grid = []
        fold.update(source_assisted=True, choice_source="LOSO_source_simulated_same_budget_validation",
            fallback_key=key, fallback_reason="insufficient internal fitting/validation labels",
            fallback_validation_labels="source/pseudo_validation_folds.json: original six folds",
            fallback_source_fit_end="2020-12-31", fallback_validation_end=fallback["validation_end"],
            local_hyperparameter_source_pool="K3", shared_hyperparameter_source_pool=bank["pool_id"])
    return dict(fold=fold, parameters=parameters, residual_validation=grid,
                selection_uses_deployment_labels=False)
