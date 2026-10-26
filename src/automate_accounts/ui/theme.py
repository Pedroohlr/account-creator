"""Tema verde do painel."""

GREEN = "#22c55e"
GREEN_SOFT = "#86efac"
GREEN_DARK = "#14532d"
RED = "#ef4444"
AMBER = "#fbbf24"

CSS = """
Screen { background: #07130b; color: #d1fae5; }
Header { background: #14532d; color: #bbf7d0; text-style: bold; }
Header HeaderIcon { color: #22c55e; }
Footer { background: #0b1f12; color: #86efac; }
Footer FooterKey { background: #0b1f12; color: #86efac; }
Footer FooterKey .footer-key--key { background: #166534; color: #f0fdf4; }

/* Abas */
TabbedContent { height: 1fr; }
Tabs { background: #0b1f12; }
Tab { color: #86efac; padding: 0 2; }
Tab:hover { color: #f0fdf4; background: #14532d; }
Tab.-active { color: #22c55e; text-style: bold; background: #0b1f12; }
Tabs Underline > .underline--bar { color: #22c55e; background: #14532d; }
TabPane { padding: 1 2; }

/* Texto */
.section { color: #22c55e; text-style: bold; margin: 1 0 0 0; }
.hint { color: #4ade80; }
.muted { color: #6ee7b7; text-style: italic; }
.label { color: #86efac; margin-top: 1; }

/* Cartões de estatística */
.cards { height: 6; margin-bottom: 1; }
StatCard {
    width: 1fr; height: 6; margin-right: 1; padding: 0 1;
    background: #0b1f12; border: round #166534; border-top: thick #22c55e;
}
StatCard .card-title { color: #86efac; text-style: bold; }
StatCard .card-value { color: #f0fdf4; text-style: bold; width: 100%; content-align: center middle; height: 3; }
StatCard.bad { border-top: thick #ef4444; }
StatCard.bad .card-value { color: #fca5a5; }
StatCard.good .card-value { color: #4ade80; }

/* Tabelas e log */
DataTable { background: #0b1f12; border: round #166534; height: 1fr; }
DataTable > .datatable--header { background: #14532d; color: #bbf7d0; text-style: bold; }
DataTable > .datatable--cursor { background: #16a34a; color: #052e16; }
DataTable > .datatable--hover { background: #14532d; }
RichLog { background: #04100a; border: round #166534; height: 1fr; }

/* Formulários */
Input { background: #04100a; border: tall #166534; color: #d1fae5; }
Input:focus { border: tall #22c55e; }
Input > .input--placeholder { color: #4b7a5a; }
Select { background: #04100a; }
SelectCurrent { background: #04100a; border: tall #166534; color: #d1fae5; }
Select:focus > SelectCurrent { border: tall #22c55e; }
SelectOverlay { background: #0b1f12; border: tall #22c55e; }
Switch { background: #0b1f12; border: tall #166534; }
Switch.-on > .switch--slider { color: #22c55e; }
.form-row { height: auto; }
#st-url { width: 72; }
#a-search { width: 44; }
#a-status { width: 22; }
.form-row Label { width: 42; padding-top: 1; color: #86efac; }
.form-row Input, .form-row Select { width: 40; }
.form-row Switch { width: auto; }
.form-row .muted { width: auto; padding: 1 0 0 2; }

/* Botões */
Button { background: #14532d; color: #f0fdf4; border: none; border-top: tall #22c55e33; border-bottom: tall #052e16; margin-right: 1; min-width: 18; }
Button:hover { background: #166534; }
Button.-primary { background: #16a34a; color: #052e16; text-style: bold; border-top: tall #4ade80; }
Button.-primary:hover { background: #22c55e; }
Button.-error { background: #7f1d1d; color: #fee2e2; }
.buttons { height: auto; margin-top: 1; }

/* Progresso */
ProgressBar { margin: 1 0; }
Bar > .bar--bar { color: #22c55e; background: #14532d; }
Bar > .bar--complete { color: #4ade80; }
PercentageStatus { color: #86efac; }

#status { color: #4ade80; text-style: bold; margin-top: 1; }
#estimate { border: round #166534; background: #0b1f12; padding: 1 2; margin-top: 1; color: #bbf7d0; height: auto; }

/* Lotes */
#b-table { height: 10; }
#b-bottom { height: 1fr; margin-top: 1; }
#b-detail { width: 62; border: round #166534; background: #0b1f12; padding: 1 2; height: 100%; overflow-y: auto; }
#b-bottom RichLog { width: 1fr; height: 100%; margin-left: 1; }
.buttons .muted { padding: 1 1 0 2; width: auto; }
#proxy-line { margin-bottom: 0; }

CountScreen { align: center middle; background: #07130bcc; }
"""
