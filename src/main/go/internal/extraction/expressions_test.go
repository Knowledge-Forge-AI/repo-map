package extraction

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

const expressionSource = `package sample
type Box[T any] struct{ Value T }
func examples(values []int, mapping map[string]int, input any) {
    _ = values[1]
    _ = values[1:2]
    _ = map[string]int{"private-literal": 1}["private-literal"]
    _ = Box[int]{Value: 1}
    _ = []byte("private-value")
    _ = input.(string)
    _ = (*Box[int]).Method
    _ = Generic[int, string]
    fmt.Println(mapping)
    switch typed := input.(type) { case string: _ = typed }
}
`

func TestParseFileExtractsBoundedReferenceAndExpressionSyntax(t *testing.T) {
	path := writeSource(t, "expressions.go", expressionSource)

	result := ParseFile(path, "sample/expressions.go")
	byKind := observationsByKind(result)
	for _, kind := range []string{
		"go.reference", "go.selector", "go.call", "go.method_expression",
		"go.construct", "go.conversion", "go.type_assertion", "go.type_switch",
		"go.index", "go.slice", "go.map_access", "go.instantiation",
	} {
		if len(byKind[kind]) == 0 {
			t.Fatalf("missing %s in %#v", kind, observationKinds(result))
		}
	}
	referenceNames := observationNameList(byKind["go.reference"])
	if containsString(referenceNames, "examples") {
		t.Fatal("function definition leaked as a reference")
	}
	for _, usedName := range []string{"values", "mapping", "input"} {
		if !containsString(referenceNames, usedName) {
			t.Fatalf("missing identifier use %q", usedName)
		}
	}
	mapAccess := byKind["go.map_access"][0]
	if mapAccess.Metadata["map_type_proven"] != true || mapAccess.Metadata["resolution"] != "syntactic" {
		t.Fatalf("map access metadata = %#v", mapAccess.Metadata)
	}
	if byKind["go.instantiation"][0].Metadata["resolution"] != "syntactic" {
		t.Fatalf("instantiation metadata = %#v", byKind["go.instantiation"][0].Metadata)
	}

	payload, err := json.Marshal(result.Observations)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"private-literal", "private-value"} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("observation payload leaked %q", forbidden)
		}
	}

	again := ParseFile(path, "sample/expressions.go")
	if !reflect.DeepEqual(result, again) {
		t.Fatal("expression observations are not deterministic")
	}
}

func containsString(values []string, wanted string) bool {
	for _, value := range values {
		if value == wanted {
			return true
		}
	}
	return false
}
