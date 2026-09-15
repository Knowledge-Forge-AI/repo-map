#!/usr/bin/env bash
# Static extraction fixture only. Do not execute.
printf '%s\n' "hello"
git status --short
docker compose ps
kubectl get pods --namespace fixture
terraform plan -out=plan.tfplan
grep "active" ./input.txt | sort | uniq
printf '%s\n' "err" |& grep err
make lint && make test || printf '%s\n' "failed"
printf '%s\n' "ok" > ./out/report.txt
printf '%s\n' "more" >> ./out/report.txt
grep "x" < ./input.txt
python3 script.py 2> ./err.log
cmd > ./out.txt 2>&1
cmd &> ./combined.log
read value <<< "literal"
FOO=bar git status
sudo env EXAMPLE_MODE=fixture apt-get install example-package
curl -fsS -H 'Authorization: Bearer FAKE_BASH_HEADER_SECRET' https://example.invalid/api
grep "x" < "$DYNAMIC_INPUT"
diff <(sort ./a.txt) >(sort ./b.txt)
