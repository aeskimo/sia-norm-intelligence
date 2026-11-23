# ADR-0001: Trennung Datenkatalog / Normwissen / Regeln
- Status: akzeptiert
- Kontext: Begriffe sind normübergreifend stabil, Normaussagen und Regeln sind ausgabe- und fundstellenabhängig.
- Entscheidung: Drei getrennte Objekttypen mit eigenen Schemas. Normaussagen und Regeln referenzieren Konzepte per ID, nie umgekehrt.
- Konsequenzen: Mehrere Normen nutzen dasselbe Konzept; Ausgabewechsel betrifft nur Normwissen/Regeln.
- Verworfen: Ein gemeinsames Modell „Norm als Datenbank".
