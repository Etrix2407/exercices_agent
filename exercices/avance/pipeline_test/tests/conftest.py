"""Affiche la note globale de chaque agent à la fin de pytest, que le test passe ou échoue."""


def pytest_terminal_summary(terminalreporter):
    reports = [report for outcome in ("passed", "failed") for report in terminalreporter.stats.get(outcome, [])]
    notes = [value for report in reports for name, value in report.user_properties if name == "note"]
    if notes:
        terminalreporter.section("Note globale des agents")
        for note in notes:
            terminalreporter.write_line(note)
