package extraction

import (
	"go/ast"
	"go/token"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

type syntaxPositions struct {
	definitions map[token.Pos]struct{}
	selectors   map[token.Pos]struct{}
}

func (context *fileContext) expressionObservations(
	file *ast.File,
) []protocol.Observation {
	positions := collectSyntaxPositions(file)
	observations := make([]protocol.Observation, 0)
	emit := func(kind string, node ast.Node, name string, metadata map[string]any) {
		observations = append(observations, context.observation(
			kind, node.Pos(), node.End(), name, "", metadata,
		))
	}
	ast.Inspect(file, func(node ast.Node) bool {
		switch typed := node.(type) {
		case *ast.Ident:
			if typed.Name == "_" || positionExcluded(typed.Pos(), positions) {
				return true
			}
			emit("go.reference", typed, typed.Name, map[string]any{
				"resolution": "unresolved",
				"role":       "identifier",
			})
		case *ast.SelectorExpr:
			emit("go.selector", typed, typed.Sel.Name, map[string]any{
				"resolution":               "syntactic",
				"base_shape":               expressionShape(typed.X),
				"package_qualified_syntax": isIdentifierExpression(typed.X),
			})
			if explicitMethodExpressionBase(typed.X) {
				emit("go.method_expression", typed, typed.Sel.Name, map[string]any{
					"resolution": "syntactic",
					"base_shape": expressionShape(typed.X),
				})
			}
		case *ast.CallExpr:
			name, direct, selector := callableSyntax(typed.Fun)
			resolution := "unknown"
			if direct || selector {
				resolution = "syntactic"
			}
			emit("go.call", typed, name, map[string]any{
				"resolution":        resolution,
				"callee_shape":      expressionShape(typed.Fun),
				"direct_identifier": direct,
				"selector_call":     selector,
				"argument_count":    len(typed.Args),
			})
			if explicitTypeExpression(typed.Fun) {
				emit("go.conversion", typed, "", map[string]any{
					"resolution":     "syntactic",
					"type_shape":     expressionShape(typed.Fun),
					"argument_count": len(typed.Args),
				})
			}
		case *ast.CompositeLit:
			emit("go.construct", typed, "", map[string]any{
				"resolution":    "syntactic",
				"type_shape":    expressionShape(typed.Type),
				"element_count": len(typed.Elts),
			})
		case *ast.TypeAssertExpr:
			if typed.Type != nil {
				emit("go.type_assertion", typed, "", map[string]any{
					"resolution": "syntactic",
					"type_shape": expressionShape(typed.Type),
				})
			}
		case *ast.TypeSwitchStmt:
			emit("go.type_switch", typed, "", map[string]any{
				"resolution": "syntactic",
				"case_count": len(typed.Body.List),
			})
		case *ast.IndexExpr:
			emit("go.index", typed, "", map[string]any{
				"resolution": "unknown",
				"base_shape": expressionShape(typed.X),
			})
			if explicitMapExpression(typed.X) {
				emit("go.map_access", typed, "", map[string]any{
					"resolution":      "syntactic",
					"map_type_proven": true,
				})
			}
		case *ast.IndexListExpr:
			emit("go.instantiation", typed, "", map[string]any{
				"resolution":          "syntactic",
				"type_argument_count": len(typed.Indices),
				"base_shape":          expressionShape(typed.X),
			})
		case *ast.SliceExpr:
			emit("go.slice", typed, "", map[string]any{
				"resolution":  "syntactic",
				"three_index": typed.Slice3,
			})
		}
		return true
	})
	return observations
}

func collectSyntaxPositions(file *ast.File) syntaxPositions {
	positions := syntaxPositions{
		definitions: make(map[token.Pos]struct{}),
		selectors:   make(map[token.Pos]struct{}),
	}
	markIdentifiers := func(identifiers []*ast.Ident) {
		for _, identifier := range identifiers {
			if identifier != nil {
				positions.definitions[identifier.Pos()] = struct{}{}
			}
		}
	}
	ast.Inspect(file, func(node ast.Node) bool {
		switch typed := node.(type) {
		case *ast.File:
			markIdentifiers([]*ast.Ident{typed.Name})
		case *ast.ImportSpec:
			markIdentifiers([]*ast.Ident{typed.Name})
		case *ast.ValueSpec:
			markIdentifiers(typed.Names)
		case *ast.TypeSpec:
			markIdentifiers([]*ast.Ident{typed.Name})
		case *ast.FuncDecl:
			markIdentifiers([]*ast.Ident{typed.Name})
		case *ast.Field:
			markIdentifiers(typed.Names)
		case *ast.LabeledStmt:
			markIdentifiers([]*ast.Ident{typed.Label})
		case *ast.AssignStmt:
			if typed.Tok == token.DEFINE {
				markExpressionIdentifiers(typed.Lhs, markIdentifiers)
			}
		case *ast.RangeStmt:
			if typed.Tok == token.DEFINE {
				markExpressionIdentifiers([]ast.Expr{typed.Key, typed.Value}, markIdentifiers)
			}
		case *ast.SelectorExpr:
			positions.selectors[typed.Sel.Pos()] = struct{}{}
		}
		return true
	})
	return positions
}

func markExpressionIdentifiers(
	expressions []ast.Expr,
	mark func([]*ast.Ident),
) {
	identifiers := make([]*ast.Ident, 0, len(expressions))
	for _, expression := range expressions {
		if identifier, ok := expression.(*ast.Ident); ok {
			identifiers = append(identifiers, identifier)
		}
	}
	mark(identifiers)
}

func positionExcluded(position token.Pos, positions syntaxPositions) bool {
	if _, ok := positions.definitions[position]; ok {
		return true
	}
	_, ok := positions.selectors[position]
	return ok
}

func callableSyntax(expression ast.Expr) (string, bool, bool) {
	switch typed := expression.(type) {
	case *ast.Ident:
		return typed.Name, true, false
	case *ast.SelectorExpr:
		return typed.Sel.Name, false, true
	default:
		return "", false, false
	}
}

func explicitTypeExpression(expression ast.Expr) bool {
	switch unwrapParens(expression).(type) {
	case *ast.ArrayType, *ast.MapType, *ast.ChanType, *ast.FuncType,
		*ast.InterfaceType, *ast.StructType:
		return true
	default:
		return false
	}
}

func explicitMethodExpressionBase(expression ast.Expr) bool {
	base := unwrapParens(expression)
	switch base.(type) {
	case *ast.StarExpr, *ast.IndexListExpr:
		return true
	default:
		return false
	}
}

func explicitMapExpression(expression ast.Expr) bool {
	base := unwrapParens(expression)
	switch typed := base.(type) {
	case *ast.CompositeLit:
		_, ok := typed.Type.(*ast.MapType)
		return ok
	case *ast.CallExpr:
		_, ok := unwrapParens(typed.Fun).(*ast.MapType)
		return ok
	default:
		return false
	}
}

func isIdentifierExpression(expression ast.Expr) bool {
	_, ok := unwrapParens(expression).(*ast.Ident)
	return ok
}
