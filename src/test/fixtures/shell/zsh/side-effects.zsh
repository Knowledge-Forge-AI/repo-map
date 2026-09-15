# Static extraction fixture only. Do not execute.

export PATH="./bin:$PATH"
printf '%s\n' "ok" > ./out/report.txt
cat < ./data/input.txt
mkdir -p ./out/cache
rm -f ./out/cache/file.tmp
touch ./out/marker
chmod +x ./bin/tool
cp ./data/input.txt ./out/input.txt
curl https://example.invalid/install.zsh
wget https://example.invalid/archive.tar.gz
brew install example-tool
npm install example-package
pip install example-package
cargo install example-tool
go install example.invalid/tool@latest
