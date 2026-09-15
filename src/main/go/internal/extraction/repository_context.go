package extraction

import (
	"go/ast"
	"go/build/constraint"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

const (
	maxBuildConstraintTags = 64
	maxBuildTagLength      = 128
)

func (context *fileContext) repositoryContextObservations(
	file *ast.File,
) []protocol.Observation {
	observations := make([]protocol.Observation, 0)
	emit := func(kind string, node ast.Node, name string, metadata map[string]any) {
		observations = append(observations, context.observation(
			kind, node.Pos(), node.End(), name, "", metadata,
		))
	}
	for _, group := range file.Comments {
		for _, comment := range group.List {
			if observation, ok := context.buildConstraintObservation(comment); ok {
				observations = append(observations, observation)
			}
			if generatedMarker(comment, file) {
				emit("go.generated_marker", comment, "generated", map[string]any{
					"resolution":   "syntactic",
					"marker_valid": true,
				})
			}
		}
	}
	for _, declaration := range file.Decls {
		switch typed := declaration.(type) {
		case *ast.GenDecl:
			observations = append(observations, context.cgoObservations(typed)...)
		case *ast.FuncDecl:
			if kind := testProfileKind(typed, context.testFile); kind != "" {
				emit(kind, typed, typed.Name.Name, map[string]any{
					"resolution":        "syntactic",
					"execution_claimed": false,
				})
			}
		}
	}
	if context.vendor {
		emit("go.vendor_package", file.Name, file.Name.Name, map[string]any{
			"resolution":     "syntactic",
			"package_name":   file.Name.Name,
			"vendor_present": true,
		})
	}
	return observations
}

func (context *fileContext) buildConstraintObservation(
	comment *ast.Comment,
) (protocol.Observation, bool) {
	if !constraint.IsGoBuild(comment.Text) && !constraint.IsPlusBuild(comment.Text) {
		return protocol.Observation{}, false
	}
	expression, err := constraint.Parse(comment.Text)
	if err != nil {
		return protocol.Observation{}, false
	}
	directive := "go:build"
	if constraint.IsPlusBuild(comment.Text) {
		directive = "+build"
	}
	tags, tagCount, truncated := constraintTags(expression)
	return context.observation(
		"go.build_constraint", comment.Pos(), comment.End(), directive, "",
		map[string]any{
			"resolution":       "syntactic",
			"directive":        directive,
			"expression_shape": constraintShape(expression),
			"tags":             tags,
			"tag_count":        tagCount,
			"tags_truncated":   truncated,
			"evaluated":        false,
		},
	), true
}

func generatedMarker(comment *ast.Comment, file *ast.File) bool {
	return ast.IsGenerated(file) && comment.Pos() < file.Package &&
		strings.HasPrefix(comment.Text, "// Code generated ") &&
		strings.HasSuffix(strings.TrimSpace(comment.Text), " DO NOT EDIT.")
}

func (context *fileContext) cgoObservations(
	declaration *ast.GenDecl,
) []protocol.Observation {
	observations := make([]protocol.Observation, 0)
	for _, candidate := range declaration.Specs {
		spec, ok := candidate.(*ast.ImportSpec)
		if !ok {
			continue
		}
		path, err := strconv.Unquote(spec.Path.Value)
		if err != nil || path != "C" {
			continue
		}
		preamble := spec.Doc
		if preamble == nil {
			preamble = declaration.Doc
		}
		observations = append(observations, context.observation(
			"go.cgo", spec.Pos(), spec.End(), "C", "",
			map[string]any{
				"resolution":       "syntactic",
				"preamble_present": preamble != nil,
				"directive_count":  cgoDirectiveCount(preamble),
				"executed":         false,
			},
		))
	}
	return observations
}

func cgoDirectiveCount(group *ast.CommentGroup) int {
	if group == nil {
		return 0
	}
	count := 0
	for _, comment := range group.List {
		for _, line := range strings.Split(comment.Text, "\n") {
			trimmed := strings.TrimSpace(line)
			trimmed = strings.TrimSpace(strings.TrimPrefix(trimmed, "/*"))
			trimmed = strings.TrimSpace(strings.TrimPrefix(trimmed, "//"))
			if strings.HasPrefix(trimmed, "#cgo ") {
				count++
			}
		}
	}
	return count
}

func testProfileKind(declaration *ast.FuncDecl, testFile bool) string {
	if !testFile || declaration.Recv != nil || declaration.Name == nil || declaration.Type.TypeParams != nil {
		return ""
	}
	name := declaration.Name.Name
	switch {
	case name == "TestMain" && testingSignature(declaration.Type, "M"):
		return "go.test_main"
	case testingName(name, "Test") && testingSignature(declaration.Type, "T"):
		return "go.test"
	case testingName(name, "Benchmark") && testingSignature(declaration.Type, "B"):
		return "go.benchmark"
	case testingName(name, "Fuzz") && testingSignature(declaration.Type, "F"):
		return "go.fuzz"
	case strings.HasPrefix(name, "Example") && emptySignature(declaration.Type):
		return "go.example"
	default:
		return ""
	}
}

func testingName(name string, prefix string) bool {
	if !strings.HasPrefix(name, prefix) || len(name) == len(prefix) {
		return false
	}
	next, _ := utf8.DecodeRuneInString(name[len(prefix):])
	return !unicode.IsLower(next)
}

func testingSignature(function *ast.FuncType, parameter string) bool {
	if logicalFieldCount(function.Params) != 1 || logicalFieldCount(function.Results) != 0 {
		return false
	}
	field := function.Params.List[0]
	pointer, ok := field.Type.(*ast.StarExpr)
	if !ok {
		return false
	}
	selector, ok := pointer.X.(*ast.SelectorExpr)
	if !ok || selector.Sel.Name != parameter {
		return false
	}
	base, ok := selector.X.(*ast.Ident)
	return ok && base.Name == "testing"
}

func emptySignature(function *ast.FuncType) bool {
	return logicalFieldCount(function.Params) == 0 &&
		logicalFieldCount(function.Results) == 0
}

func constraintTags(expression constraint.Expr) ([]string, int, bool) {
	unique := make(map[string]struct{})
	collectConstraintTags(expression, unique)
	tagCount := len(unique)
	tags := make([]string, 0, len(unique))
	truncated := false
	for tag := range unique {
		if len(tag) > maxBuildTagLength {
			tag = tag[:maxBuildTagLength]
			truncated = true
		}
		tags = append(tags, tag)
	}
	sort.Strings(tags)
	if len(tags) > maxBuildConstraintTags {
		tags = tags[:maxBuildConstraintTags]
		truncated = true
	}
	return tags, tagCount, truncated
}

func collectConstraintTags(expression constraint.Expr, tags map[string]struct{}) {
	switch typed := expression.(type) {
	case *constraint.TagExpr:
		tags[typed.Tag] = struct{}{}
	case *constraint.NotExpr:
		collectConstraintTags(typed.X, tags)
	case *constraint.AndExpr:
		collectConstraintTags(typed.X, tags)
		collectConstraintTags(typed.Y, tags)
	case *constraint.OrExpr:
		collectConstraintTags(typed.X, tags)
		collectConstraintTags(typed.Y, tags)
	}
}

func constraintShape(expression constraint.Expr) string {
	switch expression.(type) {
	case *constraint.TagExpr:
		return "tag"
	case *constraint.NotExpr:
		return "not"
	case *constraint.AndExpr:
		return "and"
	case *constraint.OrExpr:
		return "or"
	default:
		return "unknown"
	}
}
