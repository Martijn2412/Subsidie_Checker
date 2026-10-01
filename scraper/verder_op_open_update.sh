#!/usr/bin/env bash
# Haalt de gegevens uit een openstaande "Subsidie-update" (branch subsidie-update) in de
# werkmap, zodat de run verdergaat waar de vorige bleef. HEAD blijft main: de PR-stap
# daarna ziet dan alle wijzigingen ten opzichte van main (oude + nieuwe) in één keer.
set -euo pipefail
BRANCH=subsidie-update
PADEN=(regelingen.json zoekstatus.json overzicht_voorwaarden.xlsx tios data)

open=$(gh pr list --head "$BRANCH" --state open --json number --jq 'length' 2>/dev/null || echo 0)
if [ "$open" = "0" ]; then
  echo "Geen openstaande Subsidie-update: deze run start vanaf main."
  exit 0
fi
if ! git fetch -q origin "$BRANCH"; then
  echo "::warning::Branch $BRANCH niet op te halen; deze run start vanaf main."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"

# Samenvoegen met main. Bij een conflict wint de openstaande update: die is het nieuwst.
if git merge -q --no-commit --no-ff -X theirs FETCH_HEAD; then
  echo "Openstaande Subsidie-update samengevoegd met main."
else
  echo "::warning::Samenvoegen gaf een conflict; de gegevens van de openstaande update worden overgenomen."
  git merge --abort || true
  git checkout FETCH_HEAD -- "${PADEN[@]}"
fi
# HEAD terug op main, de samengevoegde bestanden blijven in de werkmap staan.
git reset -q
echo "Deze run gaat verder vanaf de openstaande Subsidie-update."
git status --short | head -20
# Laat run.py weten dat hij verdergaat, zodat de PR-tekst ook de eerdere runs toont.
[ -n "${GITHUB_ENV:-}" ] && echo "VERDER_OP_OPEN_UPDATE=1" >> "$GITHUB_ENV"
exit 0
