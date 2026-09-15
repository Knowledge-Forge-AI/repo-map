package extraction

import (
	"go/ast"
	"go/token"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

func (context *fileContext) typeObservations(
	decl *ast.GenDecl,
	spec *ast.TypeSpec,
	specIndex int,
) []protocol.Observation {
	typeObservation := context.typeObservation(decl, spec, specIndex)
	observations := []protocol.Observation{typeObservation}
	observations = append(
		observations,
		context.typeParameterObservations(spec.TypeParams, typeObservation.SourceID)...,
	)
	compositeKind := ""
	var fields *ast.FieldList
	switch typed := spec.Type.(type) {
	case *ast.StructType:
		compositeKind = "go.struct"
		fields = typed.Fields
	case *ast.InterfaceType:
		compositeKind = "go.interface"
		fields = typed.Methods
	}
	if compositeKind == "" {
		return observations
	}
	composite := context.observation(
		compositeKind,
		spec.Type.Pos(),
		spec.Type.End(),
		spec.Name.Name,
		"",
		map[string]any{
			"parent_source_id": typeObservation.SourceID,
			"field_count":      logicalFieldCount(fields),
			"embedded_count":   embeddedFieldCount(fields),
		},
	)
	observations = append(observations, composite)
	observations = append(
		observations,
		context.compositeFieldObservations(fields, composite.SourceID)...,
	)
	return observations
}

func (context *fileContext) compositeFieldObservations(
	fields *ast.FieldList,
	parentSourceID string,
) []protocol.Observation {
	if fields == nil {
		return nil
	}
	position := 0
	observations := make([]protocol.Observation, 0, logicalFieldCount(fields))
	for _, field := range fields.List {
		names := field.Names
		kind := "go.field"
		if len(names) == 0 {
			kind = "go.embedded_field"
			names = []*ast.Ident{nil}
		}
		for _, name := range names {
			nameText := ""
			if name != nil {
				nameText = name.Name
			}
			_, interfaceMethod := field.Type.(*ast.FuncType)
			observations = append(observations, context.observation(
				kind,
				field.Pos(),
				field.End(),
				nameText,
				"",
				map[string]any{
					"parent_source_id": parentSourceID,
					"position":         position,
					"name_present":     name != nil,
					"exported":         name != nil && ast.IsExported(name.Name),
					"tag_present":      field.Tag != nil,
					"interface_method": interfaceMethod,
					"type_shape":       expressionShape(field.Type),
				},
			))
			position++
		}
	}
	return observations
}

func (context *fileContext) typeParameterObservations(
	fields *ast.FieldList,
	parentSourceID string,
) []protocol.Observation {
	if fields == nil {
		return nil
	}
	position := 0
	observations := make([]protocol.Observation, 0, namedFieldCount(fields)*2)
	for _, field := range fields.List {
		for _, name := range field.Names {
			parameter := context.observation(
				"go.type_parameter",
				field.Pos(),
				field.End(),
				name.Name,
				"",
				map[string]any{
					"parent_source_id": parentSourceID,
					"position":         position,
					"constraint_shape": expressionShape(field.Type),
				},
			)
			observations = append(observations, parameter)
			observations = append(
				observations,
				context.constraintObservations(field.Type, parameter.SourceID)...,
			)
			position++
		}
	}
	return observations
}

func (context *fileContext) constraintObservations(
	expression ast.Expr,
	parentSourceID string,
) []protocol.Observation {
	terms := unionTerms(expression)
	constraint := context.observation(
		"go.constraint",
		expression.Pos(),
		expression.End(),
		"",
		"",
		map[string]any{
			"parent_source_id": parentSourceID,
			"type_shape":       expressionShape(expression),
			"union":            len(terms) > 1,
		},
	)
	observations := []protocol.Observation{constraint}
	if len(terms) < 2 {
		return observations
	}
	for position, term := range terms {
		approximation := false
		termExpression := term
		if unary, ok := term.(*ast.UnaryExpr); ok && unary.Op == token.TILDE {
			approximation = true
			termExpression = unary.X
		}
		observations = append(observations, context.observation(
			"go.union_term",
			term.Pos(),
			term.End(),
			"",
			"",
			map[string]any{
				"parent_source_id": constraint.SourceID,
				"position":         position,
				"approximation":    approximation,
				"type_shape":       expressionShape(termExpression),
			},
		))
	}
	return observations
}

func unionTerms(expression ast.Expr) []ast.Expr {
	binary, ok := expression.(*ast.BinaryExpr)
	if !ok || binary.Op != token.OR {
		return []ast.Expr{expression}
	}
	terms := unionTerms(binary.X)
	return append(terms, unionTerms(binary.Y)...)
}

func embeddedFieldCount(fields *ast.FieldList) int {
	if fields == nil {
		return 0
	}
	count := 0
	for _, field := range fields.List {
		if len(field.Names) == 0 {
			count++
		}
	}
	return count
}
