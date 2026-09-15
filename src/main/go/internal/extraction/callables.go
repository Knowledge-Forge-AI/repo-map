package extraction

import (
	"go/ast"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

type receiverDetails struct {
	name               string
	base               string
	pointer            bool
	typeParameterCount int
	shape              string
}

func (context *fileContext) callableObservations(
	decl *ast.FuncDecl,
) []protocol.Observation {
	kind := "go.function"
	receiver := receiverDetails{}
	if decl.Recv != nil && len(decl.Recv.List) > 0 {
		kind = "go.method"
		receiver = describeReceiver(decl.Recv.List[0])
	}
	metadata := map[string]any{
		"declaration_name":     decl.Name.Name,
		"exported":             ast.IsExported(decl.Name.Name),
		"variadic":             fieldListVariadic(decl.Type.Params),
		"parameter_count":      logicalFieldCount(decl.Type.Params),
		"result_count":         logicalFieldCount(decl.Type.Results),
		"type_parameter_count": namedFieldCount(decl.Type.TypeParams),
	}
	if kind == "go.method" {
		metadata["receiver_name"] = receiver.name
		metadata["receiver_base"] = receiver.base
		metadata["receiver_pointer"] = receiver.pointer
		metadata["receiver_type_parameter_count"] = receiver.typeParameterCount
		metadata["receiver_text_redacted"] = false
	}
	callable := context.observation(
		kind,
		decl.Pos(),
		decl.End(),
		decl.Name.Name,
		"",
		metadata,
	)
	observations := []protocol.Observation{callable}
	if kind == "go.method" {
		observations = append(
			observations,
			context.receiverObservation(decl.Recv.List[0], callable.SourceID, receiver),
		)
	}
	observations = append(
		observations,
		context.typeParameterObservations(decl.Type.TypeParams, callable.SourceID)...,
	)
	observations = append(
		observations,
		context.fieldObservations("go.parameter", decl.Type.Params, callable.SourceID)...,
	)
	observations = append(
		observations,
		context.fieldObservations("go.result", decl.Type.Results, callable.SourceID)...,
	)
	return observations
}

func (context *fileContext) receiverObservation(
	field *ast.Field,
	parentSourceID string,
	receiver receiverDetails,
) protocol.Observation {
	return context.observation(
		"go.receiver",
		field.Pos(),
		field.End(),
		receiver.name,
		"",
		map[string]any{
			"parent_source_id":              parentSourceID,
			"position":                      0,
			"name_present":                  receiver.name != "",
			"receiver_name":                 receiver.name,
			"receiver_base":                 receiver.base,
			"receiver_pointer":              receiver.pointer,
			"receiver_type_parameter_count": receiver.typeParameterCount,
			"receiver_text_redacted":        false,
			"type_shape":                    receiver.shape,
		},
	)
}

func (context *fileContext) fieldObservations(
	kind string,
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
		if len(names) == 0 {
			names = []*ast.Ident{nil}
		}
		for _, name := range names {
			nameText := ""
			if name != nil {
				nameText = name.Name
			}
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
					"variadic":         isEllipsis(field.Type),
					"type_shape":       expressionShape(field.Type),
				},
			))
			position++
		}
	}
	return observations
}

func describeReceiver(field *ast.Field) receiverDetails {
	details := receiverDetails{shape: expressionShape(field.Type)}
	if len(field.Names) > 0 {
		details.name = field.Names[0].Name
	}
	expression := unwrapParens(field.Type)
	if pointer, ok := expression.(*ast.StarExpr); ok {
		details.pointer = true
		expression = unwrapParens(pointer.X)
	}
	switch typed := expression.(type) {
	case *ast.IndexExpr:
		details.typeParameterCount = 1
		expression = unwrapParens(typed.X)
	case *ast.IndexListExpr:
		details.typeParameterCount = len(typed.Indices)
		expression = unwrapParens(typed.X)
	}
	if identifier, ok := expression.(*ast.Ident); ok {
		details.base = identifier.Name
	}
	return details
}

func logicalFieldCount(fields *ast.FieldList) int {
	if fields == nil {
		return 0
	}
	count := 0
	for _, field := range fields.List {
		count += max(len(field.Names), 1)
	}
	return count
}

func namedFieldCount(fields *ast.FieldList) int {
	if fields == nil {
		return 0
	}
	count := 0
	for _, field := range fields.List {
		count += len(field.Names)
	}
	return count
}

func fieldListVariadic(fields *ast.FieldList) bool {
	return fields != nil && len(fields.List) > 0 && isEllipsis(fields.List[len(fields.List)-1].Type)
}

func isEllipsis(expression ast.Expr) bool {
	_, ok := expression.(*ast.Ellipsis)
	return ok
}

func unwrapParens(expression ast.Expr) ast.Expr {
	for {
		parenthesized, ok := expression.(*ast.ParenExpr)
		if !ok {
			return expression
		}
		expression = parenthesized.X
	}
}

func expressionShape(expression ast.Expr) string {
	switch typed := expression.(type) {
	case *ast.Ident:
		return "identifier"
	case *ast.SelectorExpr:
		return "selector"
	case *ast.StarExpr:
		return "pointer"
	case *ast.ArrayType:
		if typed.Len == nil {
			return "slice"
		}
		return "array"
	case *ast.MapType:
		return "map"
	case *ast.ChanType:
		return "channel"
	case *ast.FuncType:
		return "function"
	case *ast.InterfaceType:
		return "interface"
	case *ast.StructType:
		return "struct"
	case *ast.IndexExpr:
		return "index"
	case *ast.IndexListExpr:
		return "index_list"
	case *ast.Ellipsis:
		return "ellipsis"
	case *ast.ParenExpr:
		return "parenthesized"
	default:
		return "other"
	}
}
