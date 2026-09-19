"""
Chart string tables (i18n).

All user-visible text in the generated chart is looked up from this dict,
keyed by language code. Add a new key here to support another language,
then pass it with --lang.
"""

CHART_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Figure title
        "title":             "Monte Carlo Simulation",
        # Parameters panel labels
        "param_file":        "File",
        "param_format":      "Format",
        "param_target":      "Target",
        "param_mix":         "Mix",
        "param_duration":    "Duration",
        "param_workdays":    "Work days",
        "param_holidays":    "Days off",
        "param_window":      "Hist. window",
        "param_chart":       "Chart",
        "param_certainties": "Certainties",
        "param_simulations": "Simulations",
        "param_annotations": "Annotations",
        # Parameters panel values
        "window_full":       "full",
        "window_range":      "{start} to {end}",
        "display_all":       "all",
        "none_val":          "none",
        "weeks_abbr":        "w.",        # long form (e.g. "12 w.")
        "weeks_short":       "w",         # short form used inside labels (e.g. "3.0w")
        "days_abbr":         "d.",
        # Size names (must parallel SCORES key order)
        "size_tiny":         "Very Small",
        "size_small":        "Small",
        "size_medium":       "Medium",
        "size_large":        "Large",
        "size_xlarge":       "X-Large",
        # Chart 1 — weeks distribution
        "ax1_title":         "Distribution of weeks required\n({pct:.1f}% of {n:,} simulations reach the target)",
        "ax1_xlabel":        "Weeks required to deliver the target",
        "ax1_ylabel":        "Number of simulations",
        "ax1_objective":     "Target\n{n}w",
        # Chart 2 — volume distribution
        "ax2_title":         "Volume delivered in {n_weeks} weeks ({n_workdays} work days)\n({pct:.1f}% of {n:,} simulations reach the target)",
        "ax2_xlabel":        "Points delivered in {n_weeks} weeks",
        "ax2_ylabel":        "Number of simulations",
        "ax2_target":        "Target\n{target:g} pts",
        # Chart 3 — sensitivity
        "ax3_title":         "Sensitivity to history window\n(deliver {target:g} pts in {n_weeks} w.)",
        "ax3_xlabel":        "History window (weeks) — left: full history, right: recent only",
        "ax3_ylabel":        "Probability of delivering target (%)",
        "ax3_bar_ylabel":    "Throughput (pts / week)",
        "all_label":         "All",
        "active_marker":     "↑ {n}w",
        "active_marker_all": "↑ All",
        "no_data":           "Insufficient data",
    },
    "fr": {
        # Titre de la figure
        "title":             "Simulation Monte Carlo",
        # Étiquettes du panneau de paramètres
        "param_file":        "Fichier",
        "param_format":      "Format",
        "param_target":      "Cible",
        "param_mix":         "Mix",
        "param_duration":    "Durée",
        "param_workdays":    "Jours trav.",
        "param_holidays":    "Jours off",
        "param_window":      "Fenêtre hist.",
        "param_chart":       "Graphique",
        "param_certainties": "Certitudes",
        "param_simulations": "Simulations",
        "param_annotations": "Annotations",
        # Valeurs du panneau de paramètres
        "window_full":       "complète",
        "window_range":      "{start} au {end}",
        "display_all":       "tout",
        "none_val":          "aucun",
        "weeks_abbr":        "sem.",
        "weeks_short":       "s",
        "days_abbr":         "j.",
        # Noms des tailles (parallèle aux clés de SCORES)
        "size_tiny":         "Très petit",
        "size_small":        "Petit",
        "size_medium":       "Moyen",
        "size_large":        "Grand",
        "size_xlarge":       "Très grand",
        # Graphique 1 — distribution des semaines
        "ax1_title":         "Distribution du nombre de semaines requises\n({pct:.1f} % des {n:,} simulations atteignent la cible)",
        "ax1_xlabel":        "Semaines requises pour livrer la cible",
        "ax1_ylabel":        "Nombre de simulations",
        "ax1_objective":     "Objectif\n{n}s",
        # Graphique 2 — distribution du volume
        "ax2_title":         "Distribution du volume livré en {n_weeks} semaines ({n_workdays} j. trav.)\n({pct:.1f} % des {n:,} simulations atteignent la cible)",
        "ax2_xlabel":        "Points livrés en {n_weeks} semaines",
        "ax2_ylabel":        "Nombre de simulations",
        "ax2_target":        "Cible\n{target:g} pts",
        # Graphique 3 — sensibilité
        "ax3_title":         "Sensibilité à la fenêtre d'historique\n(livrer {target:g} pts en {n_weeks} sem.)",
        "ax3_xlabel":        "Fenêtre d'historique (semaines) — gauche : tout l'historique, droite : récent seulement",
        "ax3_ylabel":        "Probabilité de livrer la cible (%)",
        "ax3_bar_ylabel":    "Throughput (pts / semaine)",
        "all_label":         "Tout",
        "active_marker":     "↑ {n}s",
        "active_marker_all": "↑ Tout",
        "no_data":           "Données insuffisantes",
    },
}
