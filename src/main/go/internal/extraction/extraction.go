// Package extraction converts Go syntax trees into bounded raw observations.
package extraction

import (
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/scanner"
	"go/token"
	"net/url"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

const (
	ExtractorVersion = "0.1.0"
	MaxDiagnostics   = 32
)

type Diagnostic struct {
	Severity string
	Code     string
	Line     int
	Message  string
}

type Result struct {
	Observations []protocol.Observation
	Diagnostics  []Diagnostic
	Truncated    bool
}

type fileContext struct {
	fset         *token.FileSet
	relative     string
	packageName  string
	testFile     bool
	generated    bool
	vendor       bool
	partialParse bool
	ordinals     map[string]int
}

// ParseFile parses one validated Go source file without type checking.
func ParseFile(path string, relative string) Result {
	fset := token.NewFileSet()
	parsed, parseErr := parser.ParseFile(
		fset,
		path,
		nil,
		parser.ParseComments|parser.AllErrors|parser.SkipObjectResolution,
	)
	result := Result{Diagnostics: parserDiagnostics(parseErr)}
	result.Truncated = parserDiagnosticCount(parseErr) > MaxDiagnostics
	if parsed == nil || parsed.Name == nil {
		return result
	}
	context := fileContext{
		fset:         fset,
		relative:     filepath.ToSlash(relative),
		packageName:  parsed.Name.Name,
		testFile:     strings.HasSuffix(relative, "_test.go"),
		generated:    ast.IsGenerated(parsed),
		vendor:       hasPathPart(filepath.ToSlash(relative), "vendor"),
		partialParse: parseErr != nil,
		ordinals:     make(map[string]int),
	}
	result.Observations = append(
		result.Observations,
		context.observation(
			"go.package",
			parsed.Package,
			parsed.Name.End(),
			parsed.Name.Name,
			"",
			map[string]any{
				"external_test_package": context.testFile && strings.HasSuffix(parsed.Name.Name, "_test"),
				"main_package":          parsed.Name.Name == "main",
				"file_count_known":      false,
			},
		),
	)
	for _, declaration := range parsed.Decls {
		switch typed := declaration.(type) {
		case *ast.GenDecl:
			result.Observations = append(
				result.Observations,
				context.declarationObservations(typed)...,
			)
		case *ast.FuncDecl:
			result.Observations = append(
				result.Observations,
				context.callableObservations(typed)...,
			)
		}
	}
	result.Observations = append(result.Observations, context.expressionObservations(parsed)...)
	result.Observations = append(result.Observations, context.controlObservations(parsed)...)
	result.Observations = append(result.Observations, context.repositoryContextObservations(parsed)...)
	result.Observations = validSpanObservations(result.Observations)
	sortObservations(result.Observations)
	return result
}

func validSpanObservations(observations []protocol.Observation) []protocol.Observation {
	valid := observations[:0]
	for _, observation := range observations {
		startOffset := observation.Metadata["start_offset"].(int)
		endOffset := observation.Metadata["end_offset"].(int)
		if observation.StartLine < 1 || observation.EndLine < observation.StartLine {
			continue
		}
		if startOffset < 0 || endOffset < startOffset {
			continue
		}
		valid = append(valid, observation)
	}
	return valid
}

func (context *fileContext) declarationObservations(decl *ast.GenDecl) []protocol.Observation {
	observations := make([]protocol.Observation, 0)
	for specIndex, spec := range decl.Specs {
		switch typed := spec.(type) {
		case *ast.ImportSpec:
			if decl.Tok != token.IMPORT {
				continue
			}
			if observation, ok := context.importObservation(decl, typed, specIndex); ok {
				observations = append(observations, observation)
			}
		case *ast.ValueSpec:
			observations = append(
				observations,
				context.valueObservations(decl, typed, specIndex)...,
			)
		case *ast.TypeSpec:
			if decl.Tok == token.TYPE {
				observations = append(
					observations,
					context.typeObservations(decl, typed, specIndex)...,
				)
			}
		}
	}
	return observations
}

func (context *fileContext) importObservation(
	decl *ast.GenDecl,
	spec *ast.ImportSpec,
	specIndex int,
) (protocol.Observation, bool) {
	importPath, err := strconv.Unquote(spec.Path.Value)
	if err != nil || importPath == "" {
		return protocol.Observation{}, false
	}
	alias := ""
	if spec.Name != nil {
		alias = spec.Name.Name
	}
	metadata := map[string]any{
		"alias":         alias,
		"blank_import":  alias == "_",
		"dot_import":    alias == ".",
		"parenthesized": decl.Lparen.IsValid(),
		"spec_index":    specIndex,
	}
	target := "go.package-ref:" + url.PathEscape(importPath)
	return context.observation(
		"go.import", spec.Pos(), spec.End(), importPath, target, metadata,
	), true
}

func (context *fileContext) valueObservations(
	decl *ast.GenDecl,
	spec *ast.ValueSpec,
	specIndex int,
) []protocol.Observation {
	kind := ""
	switch decl.Tok {
	case token.CONST:
		kind = "go.const"
	case token.VAR:
		kind = "go.var"
	default:
		return nil
	}
	observations := make([]protocol.Observation, 0, len(spec.Names))
	for nameIndex, name := range spec.Names {
		observations = append(
			observations,
			context.observation(
				kind,
				spec.Pos(),
				spec.End(),
				name.Name,
				"",
				map[string]any{
					"declaration_name": name.Name,
					"exported":         ast.IsExported(name.Name),
					"grouped":          decl.Lparen.IsValid(),
					"spec_index":       specIndex,
					"name_index":       nameIndex,
				},
			),
		)
	}
	return observations
}

func (context *fileContext) typeObservation(
	decl *ast.GenDecl,
	spec *ast.TypeSpec,
	specIndex int,
) protocol.Observation {
	typeParameterCount := 0
	if spec.TypeParams != nil {
		for _, field := range spec.TypeParams.List {
			typeParameterCount += len(field.Names)
		}
	}
	kind := "go.type"
	if spec.Assign.IsValid() {
		kind = "go.type_alias"
	}
	return context.observation(
		kind,
		spec.Pos(),
		spec.End(),
		spec.Name.Name,
		"",
		map[string]any{
			"declaration_name":     spec.Name.Name,
			"exported":             ast.IsExported(spec.Name.Name),
			"generic":              typeParameterCount > 0,
			"type_parameter_count": typeParameterCount,
			"grouped":              decl.Lparen.IsValid(),
			"spec_index":           specIndex,
		},
	)
}

func (context *fileContext) observation(
	kind string,
	start token.Pos,
	end token.Pos,
	name string,
	target string,
	metadata map[string]any,
) protocol.Observation {
	startPosition := context.fset.PositionFor(start, false)
	endPosition := context.fset.PositionFor(end, false)
	ordinal := context.ordinals[kind]
	context.ordinals[kind]++
	metadata["start_column"] = startPosition.Column
	metadata["end_column"] = endPosition.Column
	metadata["start_offset"] = startPosition.Offset
	metadata["end_offset"] = endPosition.Offset
	metadata["package_name"] = context.packageName
	metadata["ordinal"] = ordinal
	metadata["test_file"] = context.testFile
	metadata["generated"] = context.generated
	metadata["vendor"] = context.vendor
	metadata["partial_parse"] = context.partialParse
	metadata["static_only"] = true
	metadata["code_executed"] = false
	metadata["type_checked"] = false
	return protocol.Observation{
		SchemaVersion:    1,
		Kind:             kind,
		SourceID:         fmt.Sprintf("%s#%s:%d:%d:%d", context.relative, kind, startPosition.Offset, endPosition.Offset, ordinal),
		Path:             context.relative,
		Confidence:       "extracted",
		Extractor:        "repo-go-ast",
		ExtractorVersion: ExtractorVersion,
		StartLine:        startPosition.Line,
		EndLine:          endPosition.Line,
		Name:             name,
		Target:           target,
		Metadata:         metadata,
	}
}

func parserDiagnostics(parseErr error) []Diagnostic {
	if parseErr == nil {
		return nil
	}
	entries := make([]scanner.Error, 0)
	var list scanner.ErrorList
	if errors.As(parseErr, &list) {
		for _, item := range list {
			if item != nil {
				entries = append(entries, *item)
			}
		}
	} else {
		return []Diagnostic{{Severity: "warning", Code: "go-parse-error", Line: 1, Message: "syntax error"}}
	}
	seen := make(map[string]struct{})
	truncated := len(entries) > MaxDiagnostics
	diagnosticLimit := MaxDiagnostics
	if truncated {
		diagnosticLimit--
	}
	diagnostics := make([]Diagnostic, 0, min(len(entries), MaxDiagnostics))
	for _, item := range entries {
		line := max(item.Pos.Line, 1)
		message := boundedParserMessage(item.Msg)
		key := fmt.Sprintf("%d:%s", line, message)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		diagnostics = append(diagnostics, Diagnostic{
			Severity: "warning",
			Code:     "go-parse-error",
			Line:     line,
			Message:  message,
		})
		if len(diagnostics) == diagnosticLimit {
			break
		}
	}
	if truncated {
		diagnostics = append(diagnostics, Diagnostic{
			Severity: "warning",
			Code:     "go-parse-errors-truncated",
			Line:     max(entries[diagnosticLimit].Pos.Line, 1),
			Message:  "additional syntax errors omitted",
		})
	}
	return diagnostics
}

func parserDiagnosticCount(parseErr error) int {
	var list scanner.ErrorList
	if errors.As(parseErr, &list) {
		return len(list)
	}
	if parseErr != nil {
		return 1
	}
	return 0
}

func boundedParserMessage(message string) string {
	switch {
	case strings.Contains(message, "illegal character"):
		return "illegal character"
	case strings.Contains(message, "expected"):
		return "expected syntax token"
	case strings.Contains(message, "missing"):
		return "missing syntax token"
	default:
		return "syntax error"
	}
}

func hasPathPart(path string, part string) bool {
	for _, candidate := range strings.Split(path, "/") {
		if candidate == part {
			return true
		}
	}
	return false
}

func sortObservations(observations []protocol.Observation) {
	sort.SliceStable(observations, func(left int, right int) bool {
		leftMetadata := observations[left].Metadata
		rightMetadata := observations[right].Metadata
		leftStart := leftMetadata["start_offset"].(int)
		rightStart := rightMetadata["start_offset"].(int)
		if leftStart != rightStart {
			return leftStart < rightStart
		}
		leftEnd := leftMetadata["end_offset"].(int)
		rightEnd := rightMetadata["end_offset"].(int)
		if leftEnd != rightEnd {
			return leftEnd < rightEnd
		}
		if observations[left].Kind != observations[right].Kind {
			return observations[left].Kind < observations[right].Kind
		}
		leftOrdinal := leftMetadata["ordinal"].(int)
		rightOrdinal := rightMetadata["ordinal"].(int)
		if leftOrdinal != rightOrdinal {
			return leftOrdinal < rightOrdinal
		}
		return observations[left].SourceID < observations[right].SourceID
	})
}
