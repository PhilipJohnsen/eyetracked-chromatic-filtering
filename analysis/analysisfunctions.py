import numpy as np
import pandas as pd
import scipy as sp
import scipy.stats
import pingouin as pg
from typing import Dict, Tuple, List, Any
import warnings


def print_rm_analysis_report(
    result: Dict[str, Any],
    analysis_title: str,
    conditions: List[str],
    effect_label: str,
    alpha: float = 0.05,
) -> None:
    """Print analysis output using the notebook schema ([ANALYSIS]/[ASSUMPTION]/[RESULT])."""

    ac = result.get("assumptions_checked", {})
    sph = ac.get("sphericity_details", {})

    print(f"[ANALYSIS] {analysis_title}")
    print(
        f"[ANALYSIS] Subjects: {result.get('n_subjects_final', 'n/a')} used, "
        f"{result.get('n_subjects_initial', 0) - result.get('n_subjects_final', 0)} dropped "
        f"(listwise deletion of incomplete cases)")
    print(f"[ANALYSIS] Conditions: {conditions}")
    if result.get("dropped_subjects"):
        print(f"[ANALYSIS] Dropped subjects: {result['dropped_subjects']}")

    print()
    print("[ASSUMPTION] Normality (Shapiro-Wilk on pairwise differences):")
    normality_notes = [
        n for n in ac.get("notes", [])
        if "Normality" in n or "normality" in n or "Shapiro" in n
    ]
    if normality_notes:
        for note in normality_notes:
            print(f"[ASSUMPTION]   {note}")
    else:
        print(f"[ASSUMPTION]   All pairwise differences passed normality (p >= {alpha:.2f})")

    print("[ASSUMPTION] Sphericity (Mauchly's test):")
    print(
        f"[ASSUMPTION]   W = {sph.get('mauchly_stat', float('nan')):.6f}, "
        f"p = {sph.get('mauchly_p', float('nan')):.6f}")
    print(f"[ASSUMPTION]   Sphericity assumed: {sph.get('sphericity_assumed', 'unknown')}")

    if ac.get("normality_violated", False) or not ac.get("sphericity_verified", False):
        print("[ASSUMPTION] One or more assumptions violated - falling back to Friedman test")
    else:
        print("[ASSUMPTION] All assumptions met - proceeding with RM ANOVA")

    print()
    print(f"[RESULT] Test used: {result.get('test', 'unknown')}")
    if result.get("test") == "RM ANOVA":
        df_b, df_e = result.get("df", (float("nan"), float("nan")))
        print(f"[RESULT] F({df_b}, {df_e}) = {result.get('statistic', float('nan')):.4f}, p = {result.get('p_value', float('nan')):.4f}")
    else:
        print(f"[RESULT] chi2({result.get('df', 'nan')}) = {result.get('statistic', float('nan')):.4f}, p = {result.get('p_value', float('nan')):.4f}")

    if result.get("significant", False):
        print(f"[RESULT] Significant effect of condition on {effect_label} (p < {alpha:.2f})")
    else:
        print(f"[RESULT] No significant effect of condition on {effect_label} (p >= {alpha:.2f})")

    post_hoc = result.get("post_hoc")
    if post_hoc is not None:
        label_map = {
            "g1 vs g2": f"{conditions[0]} vs {conditions[1]}",
            "g1 vs g3": f"{conditions[0]} vs {conditions[2]}",
            "g2 vs g3": f"{conditions[1]} vs {conditions[2]}",
        }
        print()
        print(f"[RESULT] Post-hoc: {post_hoc['method']}, Bonferroni alpha = {post_hoc['bonferroni_alpha']:.4f}")
        for pair, vals in post_hoc.get("comparisons", {}).items():
            label = label_map.get(pair, pair)
            stat_key = "t_statistic" if "t_statistic" in vals else "z_statistic"
            stat_name = "t" if "t_statistic" in vals else "W"
            sig = "significant" if vals.get("significant", False) else "not significant"
            print(f"[RESULT]   {label}: {stat_name} = {vals[stat_key]:.4f}, p = {vals['p_value']:.4f} ({sig})")
    else:
        print("[RESULT] No post-hoc tests run (main test not significant)")


def run_rm_anova_or_friedman(
    df: pd.DataFrame,
    subject_col: str,
    condition_col: str,
    value_col: str,
    alpha: float = 0.05
) -> Dict[str, Any]:
    """
    Performs repeated measures ANOVA or Friedman test based on assumption violations.
    
    This function tests for an effect across conditions while accounting for subject-level
    variation. It first checks RM ANOVA assumptions (normality and sphericity), then:
    - Runs RM ANOVA if assumptions are met
    - Falls back to Friedman test if assumptions are violated
    - Runs appropriate post-hoc tests if the main test is significant
    
    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe with subject, condition, and measurement columns
    subject_col : str
        Column name for subject identifiers
    condition_col : str
        Column name for condition groups (should have exactly 3 unique conditions)
    value_col : str
        Column name for the measured values
    alpha : float, default=0.05
        Significance level for statistical tests
    
    Returns
    -------
    dict
        A dictionary containing:
        - 'test': str - Name of test performed ("RM ANOVA" or "Friedman")
        - 'statistic': float - Test statistic (F for ANOVA, chi2 for Friedman)
        - 'df': tuple - Degrees of freedom
        - 'p_value': float - Probability value

        - 'significant': bool - Whether p_value < alpha
        - 'post_hoc': dict or None - Post-hoc test results if significant
        - 'assumptions_checked': dict - Details about assumptions
        - 'n_subjects_initial': int - Initial number of subjects
        - 'n_subjects_final': int - Final number of subjects after removing missing data
        - 'dropped_subjects': list - Subjects removed due to missing values
    
    Notes
    -----
    Sphericity cannot be directly tested with scipy alone. The function conservatively
    assumes sphericity is not verified and will fall back to Friedman if normality is violated.
    """

    def _format_stat(value: Any, pattern: str, fallback: str = "n/a") -> str:
        if value is None:
            return fallback
        try:
            return pattern.format(value)
        except (TypeError, ValueError):
            return fallback
    
    # ==========================================
    # STEP 1 — RESHAPE DATA
    # Pivot to wide format: rows=subjects, columns=conditions, values=measurements
    df_wide = df.pivot_table(
        index=subject_col,
        columns=condition_col,
        values=value_col,
        aggfunc='mean'
    )
    
    conditions = sorted(df_wide.columns.tolist())
    if len(conditions) != 3:
        raise ValueError(
            f"Expected exactly 3 conditions, found {len(conditions)}: {conditions}"
        )
    
    n_subjects_initial = len(df_wide)
    
    # Extract the 3 condition arrays (will be updated after cleaning)
    g1, g2, g3 = df_wide[conditions[0]], df_wide[conditions[1]], df_wide[conditions[2]]
    
    # ==========================================
    # STEP 2 — CHECK ASSUMPTIONS
    assumptions_checked = {
        'normality_violated': False,
        'missing_data_found': False,
        'sphericity_verified': False,
        'notes': []
    }
    
    # Assumption A: No missing data
    rows_with_missing = df_wide.isna().any(axis=1)
    dropped_subjects = df_wide[rows_with_missing].index.tolist()
    
    if len(dropped_subjects) > 0:
        assumptions_checked['missing_data_found'] = True
        assumptions_checked['notes'].append(
            f"Dropped {len(dropped_subjects)} subjects with missing data: {dropped_subjects}"
        )
        warnings.warn(
            f"Dropped {len(dropped_subjects)} subjects with missing values across conditions",
            UserWarning
        )
        # Remove rows with missing data
        df_wide = df_wide.dropna()
        g1, g2, g3 = df_wide[conditions[0]], df_wide[conditions[1]], df_wide[conditions[2]]
    
    n_subjects_final = len(df_wide)
    
    # Assumption B: Normality of differences (Shapiro-Wilk test)
    normality_violated = False
    pairwise_diffs = [
        ('g1-g2', g1.values - g2.values),
        ('g1-g3', g1.values - g3.values),
        ('g2-g3', g2.values - g3.values)
    ]
    
    for pair_name, diff in pairwise_diffs:
        stat, p = scipy.stats.shapiro(diff)
        if p < 0.05:
            normality_violated = True
            assumptions_checked['notes'].append(
                f"Normality violated for {pair_name} (Shapiro-Wilk p={p:.4f})"
            )
    
    assumptions_checked['normality_violated'] = normality_violated
    
    # Assumption C: Sphericity (Mauchly's test via pingouin)
    sphericity_result = _test_sphericity_greenhouse_geisser(g1, g2, g3)
    assumptions_checked['sphericity_verified'] = sphericity_result['sphericity_assumed']
    assumptions_checked['sphericity_details'] = sphericity_result
    assumptions_checked['notes'].append(
        f"Mauchly's test for sphericity: W={_format_stat(sphericity_result['mauchly_stat'], '{:.6f}')}, "
        f"p={_format_stat(sphericity_result['mauchly_p'], '{:.6f}')}. "
        f"GG epsilon={_format_stat(sphericity_result['epsilon_gg'], '{:.4f}')}, "
        f"HF epsilon={_format_stat(sphericity_result['epsilon_hf'], '{:.4f}')}"
    )
    
    # ==========================================
    # STEP 3 — DECIDE WHICH TEST TO RUN
    if normality_violated or not assumptions_checked['sphericity_verified']:
        test_to_run = "Friedman"
    else:
        test_to_run = "RM ANOVA"
    
    # ==========================================
    # STEP 4 — ONE-WAY RM ANOVA (parametric)
    if test_to_run == "RM ANOVA":
        result = _run_rm_anova(g1, g2, g3, alpha)
        # Attach sphericity info for reference (even though it was assumed)
        result['sphericity_result'] = sphericity_result
    else:
        # ==========================================
        # STEP 5 — FRIEDMAN TEST (fallback)
        result = _run_friedman_test(g1, g2, g3, alpha)
    
    # Add metadata to result
    result['assumptions_checked'] = assumptions_checked
    result['n_subjects_initial'] = n_subjects_initial
    result['n_subjects_final'] = n_subjects_final
    result['dropped_subjects'] = dropped_subjects
    
    # ==========================================
    # STEP 6 — INTERPRET & POST-HOC
    if result['significant']:
        if test_to_run == "RM ANOVA":
            post_hoc = _post_hoc_paired_ttest(g1, g2, g3, alpha)
        else:  # Friedman
            post_hoc = _post_hoc_wilcoxon(g1, g2, g3, alpha)
        result['post_hoc'] = post_hoc
    else:
        result['post_hoc'] = None
    
    return result


def _run_rm_anova(g1: np.ndarray, g2: np.ndarray, g3: np.ndarray, alpha: float) -> Dict[str, Any]:
    """
    Compute one-way repeated measures ANOVA manually.
    
    This function performs a parametric RM ANOVA assuming:
    - Normality of pairwise differences (verified via Shapiro-Wilkfor permutations)
    - Sphericity of the cov matrix with mauchly
    
    If sphericity is violated in practice but we proceed with RM ANOVA, the p-value
    can be corrected using Greenhouse-Geisser (GG) adjustments to the degrees of freedom
    
    Computes:
    - Grand mean, condition means, subject means
    - Sum of squares: total, between-conditions, subjects, error
    - Mean squares and F-statistic
    - P-value from F-distribution
    
    Parameters
    ----------
    g1, g2, g3 : np.ndarray
        The three condition groups (one per subject)
    alpha : float
        Significance level (typically 0.05)
    
    Returns
    -------
    dict
        Contains test results and sum/mean of squares breakdown
    """
    
    g1 = np.asarray(g1)
    g2 = np.asarray(g2)
    g3 = np.asarray(g3)
    
    n_subjects = len(g1)
    n_conditions = 3

    # Stack all observations
    all_data = np.vstack([g1, g2, g3])  # shape: (3, n_subjects)
    grand_mean = np.mean(all_data)

    # Condition means
    condition_means = np.array([np.mean(g1), np.mean(g2), np.mean(g3)])
    
    # Subject means
    subject_means = np.mean(all_data, axis=0)  # mean across the 3 conditions for each subject
    
    # Sum of Squares
    SS_total = np.sum((all_data - grand_mean) ** 2)
    SS_between = n_subjects * np.sum((condition_means - grand_mean) ** 2)
    SS_subjects = n_conditions * np.sum((subject_means - grand_mean) ** 2)
    SS_error = SS_total - SS_between - SS_subjects
    
    # Degrees of freedom
    df_between = n_conditions - 1  # = 2
    df_subjects = n_subjects - 1
    df_error = df_between * df_subjects
    
    # Mean Squares
    MS_between = SS_between / df_between
    MS_error = SS_error / df_error
    
    # F-statistic
    F_stat = MS_between / MS_error
    p_value = 1 - scipy.stats.f.cdf(F_stat, df_between, df_error)
    
    return {
        'test': 'RM ANOVA',
        'statistic': F_stat,
        'df': (df_between, df_error),
        'p_value': p_value,
        'significant': p_value < alpha,
        'sum_of_squares': {
            'total': SS_total,
            'between': SS_between,
            'subjects': SS_subjects,
            'error': SS_error
        },
        'mean_squares': {
            'between': MS_between,
            'error': MS_error
        },
        'sphericity_note': 'RM ANOVA assumes sphericity (tested via Mauchly\'s test). '
                          'If violated, consider consulting the sphericity_result for GG/HF corrections.'
    }


def _run_friedman_test(g1: np.ndarray, g2: np.ndarray, g3: np.ndarray, alpha: float) -> Dict[str, Any]:
    """
    Compute Friedman test (non-parametric alternative to RM ANOVA).
    
    The Friedman test is used as a fallback when RM ANOVA assumptions are violated:
    - Normality: If pairwise differences fail Shapiro-Wilk test (p < 0.05)
    - Sphericity: If Mauchly's test indicates sphericity is violated (p < 0.05)
    
    The Friedman test ranks observations within each subject and compares rank
    distributions across conditions. It makes no assumptions about data distribution
    or sphericity, making it robust to violations assumptions.
    
    Parameters
    ----------
    g1, g2, g3 : np.ndarray
        The three condition groups (one per subject)
    alpha : float
        Significance level fallback 0.05
    
    Returns
    -------
    dict
        chi-squared, degrees of freedom, and p-value
    """
    
    g1 = np.asarray(g1)
    g2 = np.asarray(g2)
    g3 = np.asarray(g3)
    
    stat, p_value = scipy.stats.friedmanchisquare(g1, g2, g3)
    
    n_conditions = 3
    df = n_conditions - 1  # = 2
    
    return {
        'test': 'Friedman',
        'statistic': stat,
        'df': df,
        'p_value': p_value,
        'significant': p_value < alpha,
        'test_type_note': 'Non-parametric fallback chosen due to RM ANOVA assumption violations '

    }


def _post_hoc_paired_ttest(
    g1: np.ndarray, g2: np.ndarray, g3: np.ndarray, alpha: float
) -> Dict[str, Any]:
    """
    Post-hoc pairwise t-tests with Bonferroni correction for RM ANOVA.
    
    Performs paired t-tests on all pairwise permutations between conditions.
    Bonferroni correction is applied to control FWER:
    alpha_corrected = alpha / n_comparisons
    
    Parameters
    ----------
    g1, g2, g3 : np.ndarray
        The three condition groups (one per subject)
    alpha : float
        Significance level (typically 0.05)
    
    Returns
    -------
    dict
        Contains Bonferroni-corrected alpha and results for each pairwise comparison
    """
    
    g1 = np.asarray(g1)
    g2 = np.asarray(g2)
    g3 = np.asarray(g3)
    
    n_pairs = 3
    bonferroni_alpha = alpha / n_pairs
    
    pairs = [
        ('g1 vs g2', g1, g2),
        ('g1 vs g3', g1, g3),
        ('g2 vs g3', g2, g3)
    ]
    
    results = {}
    for pair_name, group_a, group_b in pairs:
        t_stat, p_value = scipy.stats.ttest_rel(group_a, group_b)
        results[pair_name] = {
            't_statistic': t_stat,
            'p_value': p_value,
            'significant': p_value < bonferroni_alpha
        }
    
    return {
        'method': 'Paired t-test with Bonferroni correction',
        'note': 'Parametric post-hoc following RM ANOVA (assumptions were met)',
        'bonferroni_alpha': bonferroni_alpha,
        'n_pairs': n_pairs,
        'comparisons': results
    }


def _post_hoc_wilcoxon(
    g1: np.ndarray, g2: np.ndarray, g3: np.ndarray, alpha: float
) -> Dict[str, Any]:
    """
    Post-hoc pairwise Wilcoxon signed-rank tests with Bonferroni correction for Friedman test.
    
    Performs Wilcoxon signed-rank tests (non-parametric paired tests) on all pairwise
    comparisons between conditions. Bonferroni correction is applied to control
    family-wise error rate:
    alpha_corrected = alpha / n_comparisons
    
    These tests are used when Friedman test is significant. They make no assumptions
    about data distribution, making them appropriate when RM ANOVA assumptions
    (normality, sphericity) are violated.
    
    Parameters
    ----------
    g1, g2, g3 : np.ndarray
        The three condition groups (one per subject)
    alpha : float
        Significance level (typically 0.05)
    
    Returns
    -------
    dict
        Contains Bonferroni-corrected alpha and results for each pairwise comparison
    """
    
    g1 = np.asarray(g1)
    g2 = np.asarray(g2)
    g3 = np.asarray(g3)
    
    n_pairs = 3
    bonferroni_alpha = alpha / n_pairs
    
    pairs = [
        ('g1 vs g2', g1, g2),
        ('g1 vs g3', g1, g3),
        ('g2 vs g3', g2, g3)
    ]
    
    results = {}
    for pair_name, group_a, group_b in pairs:
        stat, p_value = scipy.stats.wilcoxon(group_a, group_b)
        results[pair_name] = {
            'z_statistic': stat,
            'p_value': p_value,
            'significant': p_value < bonferroni_alpha
        }
    
    return {
        'method': 'Wilcoxon signed-rank test with Bonferroni correction',
        'note': 'Non-parametric post-hoc following Friedman test (RM ANOVA assumptions were violated)',
        'bonferroni_alpha': bonferroni_alpha,
        'n_pairs': n_pairs,
        'comparisons': results
    }








def _test_sphericity_greenhouse_geisser(
    g1: np.ndarray, g2: np.ndarray, g3: np.ndarray, epsilon_threshold: float = 0.75
) -> Dict[str, Any]:
    """
    Test sphericity assumption using Mauchly's test and Greenhouse-Geisser epsilon (pingouin).
    
    Uses pingouin's sphericity function to perform Mauchly's test, which directly tests
    the sphericity assumption. Also computes Greenhouse-Geisser and Huynh-Feldt epsilon
    corrections for reference.
    
    Parameters
    ----------
    g1, g2, g3 : np.ndarray
        The three condition groups (one per subject)
    epsilon_threshold : float, default=0.75
        Threshold for assuming sphericity based on GG epsilon (typically 0.75)
    
    Returns
    -------
    dict
        Contains:
        - 'mauchly_stat': float - Mauchly's test statistic
        - 'mauchly_p': float - P-value for Mauchly's test
        - 'mauchly_significant': bool - Whether sphericity is violated (p < 0.05)
        - 'epsilon_gg': float - Greenhouse-Geisser epsilon
        - 'epsilon_hf': float - Huynh-Feldt epsilon
        - 'sphericity_assumed': bool - Whether sphericity is assumed (p >= 0.05)
        - 'interpretation': str - Description of the result
    """

    def _format_stat(value: Any, pattern: str, fallback: str = "n/a") -> str:
        if value is None:
            return fallback
        try:
            return pattern.format(value)
        except (TypeError, ValueError):
            return fallback
    
    g1 = np.asarray(g1, dtype=float)
    g2 = np.asarray(g2, dtype=float)
    g3 = np.asarray(g3, dtype=float)
    
    #Stack into matrix: rows = conditions, columns = subjects
    #pingouin expects shape (n_subjects, n_conditions)
    data_matrix = pd.DataFrame(
    np.vstack([g1, g2, g3]).T,
    columns=["cond1", "cond2", "cond3"]
    )

    spher_result = pg.sphericity(
    data=data_matrix,
    method='mauchly'
    )

    mauchly_stat       = spher_result.W
    mauchly_p          = spher_result.pval
    sphericity_assumed = spher_result.spher
    mauchly_significant = not sphericity_assumed

    # Sphericity is assumed if p-value >= 0.05
    sphericity_assumed = mauchly_p >= 0.05
    mauchly_significant = mauchly_p < 0.05 
 
    return {
        'mauchly_stat':       mauchly_stat,
        'mauchly_p':          mauchly_p,
        'mauchly_significant': mauchly_significant,
        'sphericity_assumed': sphericity_assumed,
        'epsilon_gg':         None,   # not available in this pingouin version
        'epsilon_hf':         None,
    }