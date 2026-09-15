package extraction

import (
	"reflect"
	"testing"
)

const compositeSource = `package sample
type Embedded struct{}
type Pair[K comparable, V ~int | ~int64] struct {
    Zeta, Alpha V
    *Embedded
    Tagged string ` + "`json:\"tagged\"`" + `
}
type Service interface {
    Read(input string) (string, error)
    Embedded
}
func Convert[T ~int | ~int64](value T) T { return value }
`

func TestParseFileExtractsCompositeAndGenericHierarchy(t *testing.T) {
	path := writeSource(t, "composites.go", compositeSource)

	result := ParseFile(path, "sample/composites.go")
	byKind := observationsByKind(result)
	for _, kind := range []string{
		"go.struct", "go.interface", "go.field", "go.embedded_field",
		"go.type_parameter", "go.constraint", "go.union_term",
	} {
		if len(byKind[kind]) == 0 {
			t.Fatalf("missing %s in %#v", kind, observationKinds(result))
		}
	}
	pair := observationNamed(byKind["go.struct"], "Pair")
	assertMetadata(t, pair.Metadata, map[string]any{
		"parent_source_id": observationNamed(byKind["go.type"], "Pair").SourceID,
		"field_count":      4,
		"embedded_count":   1,
	})
	fields := childObservations(byKind["go.field"], pair.SourceID)
	if names := observationNameList(fields); !reflect.DeepEqual(names, []string{"Zeta", "Alpha", "Tagged"}) {
		t.Fatalf("field order = %#v", names)
	}
	if fields[2].Metadata["tag_present"] != true {
		t.Fatalf("tag metadata = %#v", fields[2].Metadata)
	}
	typeParameter := observationNamed(byKind["go.type_parameter"], "V")
	constraints := childObservations(byKind["go.constraint"], typeParameter.SourceID)
	if len(constraints) != 1 || constraints[0].Metadata["union"] != true {
		t.Fatalf("constraints = %#v", constraints)
	}
	terms := childObservations(byKind["go.union_term"], constraints[0].SourceID)
	if len(terms) != 2 || terms[0].Metadata["approximation"] != true {
		t.Fatalf("union terms = %#v", terms)
	}

	again := ParseFile(path, "sample/composites.go")
	if !reflect.DeepEqual(result, again) {
		t.Fatal("composite observations are not deterministic")
	}
}
