package extraction

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

const controlSource = `package sample
func control(ch chan int, done <-chan int, flag bool) {
    closure := func(value int) int { return value }
    go closure(1)
    defer closure(2)
    ch <- 3
    _ = <-done
    select { case ch <- 4: case <-done: default: }
    if flag { panic("private-panic") }
    _ = recover()
    for { break }
    for { continue }
    goto Exit
Exit:
    _ = func() {}()
}
`

func TestParseFileExtractsControlAndConcurrencySyntax(t *testing.T) {
	path := writeSource(t, "control.go", controlSource)

	result := ParseFile(path, "sample/control.go")
	byKind := observationsByKind(result)
	for _, kind := range []string{
		"go.closure", "go.goroutine", "go.defer", "go.send", "go.receive",
		"go.select", "go.panic", "go.recover", "go.return", "go.break",
		"go.continue", "go.goto", "go.dynamic",
	} {
		if len(byKind[kind]) == 0 {
			t.Fatalf("missing %s in %#v", kind, observationKinds(result))
		}
	}
	if byKind["go.select"][0].Metadata["clause_count"] != 3 {
		t.Fatalf("select metadata = %#v", byKind["go.select"][0].Metadata)
	}
	if byKind["go.panic"][0].Metadata["resolution"] != "unresolved" {
		t.Fatalf("panic metadata = %#v", byKind["go.panic"][0].Metadata)
	}
	if byKind["go.dynamic"][0].Metadata["reason"] != "dynamic_callee" {
		t.Fatalf("dynamic metadata = %#v", byKind["go.dynamic"][0].Metadata)
	}
	payload, err := json.Marshal(result.Observations)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(payload), "private-panic") {
		t.Fatal("control observation leaked a literal")
	}

	again := ParseFile(path, "sample/control.go")
	if !reflect.DeepEqual(result, again) {
		t.Fatal("control observations are not deterministic")
	}
}
