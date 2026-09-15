package extraction

import (
	"go/ast"
	"go/parser"
	"reflect"
	"testing"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

const callableSource = `package sample

func Exported[T any](first int, zeta, alpha string, rest ...byte) (int, error) { return 0, nil }
func private() {}
type Box[T any] struct{}
func (box *Box[T]) Transform(values []T, apply func(T) T) (out T, ok bool) { return out, ok }
func (Box[T]) Value(input map[string]int) chan<- int { return nil }
func (*Box[T]) Reset() {}
`

func TestParseFileExtractsCallableHierarchyAndStructuredShapes(t *testing.T) {
	path := writeSource(t, "callables.go", callableSource)

	result := ParseFile(path, "sample/callables.go")
	byKind := observationsByKind(result)

	if len(byKind["go.function"]) != 2 || len(byKind["go.method"]) != 3 {
		t.Fatalf("callables = %#v", observationKinds(result))
	}
	if len(byKind["go.receiver"]) != 3 {
		t.Fatalf("receivers = %d", len(byKind["go.receiver"]))
	}
	if len(byKind["go.parameter"]) != 7 || len(byKind["go.result"]) != 5 {
		t.Fatalf("parameters/results = %d/%d", len(byKind["go.parameter"]), len(byKind["go.result"]))
	}

	exported := observationNamed(byKind["go.function"], "Exported")
	assertMetadata(t, exported.Metadata, map[string]any{
		"declaration_name":     "Exported",
		"exported":             true,
		"variadic":             true,
		"parameter_count":      4,
		"result_count":         2,
		"type_parameter_count": 1,
	})

	transform := observationNamed(byKind["go.method"], "Transform")
	assertMetadata(t, transform.Metadata, map[string]any{
		"receiver_name":                 "box",
		"receiver_base":                 "Box",
		"receiver_pointer":              true,
		"receiver_type_parameter_count": 1,
		"receiver_text_redacted":        false,
	})

	receiver := childObservations(byKind["go.receiver"], transform.SourceID)[0]
	assertMetadata(t, receiver.Metadata, map[string]any{
		"position":         0,
		"name_present":     true,
		"receiver_base":    "Box",
		"receiver_pointer": true,
		"type_shape":       "pointer",
	})
	parameters := childObservations(byKind["go.parameter"], exported.SourceID)
	if names := observationNameList(parameters); !reflect.DeepEqual(names, []string{"first", "zeta", "alpha", "rest"}) {
		t.Fatalf("parameter names = %#v", names)
	}
	if got := metadataList(parameters, "type_shape"); !reflect.DeepEqual(got, []any{"identifier", "identifier", "identifier", "ellipsis"}) {
		t.Fatalf("parameter shapes = %#v", got)
	}
	if parameters[3].Metadata["variadic"] != true {
		t.Fatalf("variadic parameter = %#v", parameters[3].Metadata)
	}
	results := childObservations(byKind["go.result"], exported.SourceID)
	if names := observationNameList(results); !reflect.DeepEqual(names, []string{"", ""}) {
		t.Fatalf("result names = %#v", names)
	}
	if results[1].Metadata["name_present"] != false || results[1].Metadata["position"] != 1 {
		t.Fatalf("unnamed result = %#v", results[1])
	}

	again := ParseFile(path, "sample/callables.go")
	if !reflect.DeepEqual(result, again) {
		t.Fatal("callable observations are not deterministic")
	}
}

func TestExpressionShapeUsesOnlyBoundedASTCategories(t *testing.T) {
	cases := map[string]string{
		"T":                "identifier",
		"pkg.T":            "selector",
		"*T":               "pointer",
		"[3]T":             "array",
		"[]T":              "slice",
		"map[string]T":     "map",
		"chan<- T":         "channel",
		"func(T) error":    "function",
		"interface{ M() }": "interface",
		"struct{ X int }":  "struct",
		"Generic[T]":       "index",
		"Generic[A, B]":    "index_list",
		"(T)":              "parenthesized",
		"~T":               "other",
	}
	for source, expected := range cases {
		t.Run(expected, func(t *testing.T) {
			expression, err := parser.ParseExpr(source)
			if err != nil {
				t.Fatal(err)
			}
			if actual := expressionShape(expression); actual != expected {
				t.Fatalf("expressionShape() = %q, want %q", actual, expected)
			}
		})
	}
	if expressionShape(&ast.Ellipsis{}) != "ellipsis" {
		t.Fatal("ellipsis shape was not normalized")
	}
}

func TestPartialCallableChildrenNeverReferenceAnOmittedParent(t *testing.T) {
	path := writeSource(
		t,
		"partial-callable.go",
		"package sample\nfunc Complete(value int) {}\nfunc Incomplete(value int) (string, error) {\n",
	)

	result := ParseFile(path, "sample/partial-callable.go")
	parents := make(map[string]struct{})
	for _, observation := range result.Observations {
		if observation.Kind == "go.function" || observation.Kind == "go.method" {
			parents[observation.SourceID] = struct{}{}
		}
	}
	for _, observation := range result.Observations {
		parent, hasParent := observation.Metadata["parent_source_id"]
		if !hasParent {
			continue
		}
		if _, ok := parents[parent.(string)]; !ok {
			t.Fatalf("dangling callable child = %#v", observation)
		}
	}
}

func observationsByKind(result Result) map[string][]protocol.Observation {
	byKind := make(map[string][]protocol.Observation)
	for _, observation := range result.Observations {
		byKind[observation.Kind] = append(byKind[observation.Kind], observation)
	}
	return byKind
}

func observationNamed(observations []protocol.Observation, name string) protocol.Observation {
	for _, observation := range observations {
		if observation.Name == name {
			return observation
		}
	}
	return protocol.Observation{}
}

func childObservations(
	observations []protocol.Observation,
	parentSourceID string,
) []protocol.Observation {
	children := make([]protocol.Observation, 0)
	for _, observation := range observations {
		if observation.Metadata["parent_source_id"] == parentSourceID {
			children = append(children, observation)
		}
	}
	return children
}

func observationNameList(observations []protocol.Observation) []string {
	names := make([]string, 0, len(observations))
	for _, observation := range observations {
		names = append(names, observation.Name)
	}
	return names
}

func metadataList(observations []protocol.Observation, key string) []any {
	values := make([]any, 0, len(observations))
	for _, observation := range observations {
		values = append(values, observation.Metadata[key])
	}
	return values
}

func assertMetadata(t *testing.T, actual map[string]any, expected map[string]any) {
	t.Helper()
	for key, value := range expected {
		if !reflect.DeepEqual(actual[key], value) {
			t.Fatalf("metadata[%q] = %#v, want %#v", key, actual[key], value)
		}
	}
}
