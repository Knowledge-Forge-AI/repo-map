package extraction

import (
	"go/ast"
	"go/token"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

func (context *fileContext) controlObservations(
	file *ast.File,
) []protocol.Observation {
	observations := make([]protocol.Observation, 0)
	emit := func(kind string, node ast.Node, name string, metadata map[string]any) {
		observations = append(observations, context.observation(
			kind, node.Pos(), node.End(), name, "", metadata,
		))
	}
	ast.Inspect(file, func(node ast.Node) bool {
		switch typed := node.(type) {
		case *ast.FuncLit:
			emit("go.closure", typed, "", map[string]any{
				"resolution":      "syntactic",
				"parameter_count": logicalFieldCount(typed.Type.Params),
				"result_count":    logicalFieldCount(typed.Type.Results),
				"captures_known":  false,
			})
		case *ast.GoStmt:
			emit("go.goroutine", typed, callableNodeName(typed.Call.Fun), map[string]any{
				"resolution":   "syntactic",
				"callee_shape": expressionShape(typed.Call.Fun),
			})
		case *ast.DeferStmt:
			emit("go.defer", typed, callableNodeName(typed.Call.Fun), map[string]any{
				"resolution":   "syntactic",
				"callee_shape": expressionShape(typed.Call.Fun),
			})
		case *ast.SendStmt:
			emit("go.send", typed, "", map[string]any{
				"resolution":    "syntactic",
				"channel_shape": expressionShape(typed.Chan),
				"value_shape":   expressionShape(typed.Value),
			})
		case *ast.UnaryExpr:
			if typed.Op == token.ARROW {
				emit("go.receive", typed, "", map[string]any{
					"resolution":    "syntactic",
					"channel_shape": expressionShape(typed.X),
				})
			}
		case *ast.SelectStmt:
			emit("go.select", typed, "", map[string]any{
				"resolution":   "syntactic",
				"clause_count": len(typed.Body.List),
			})
		case *ast.ReturnStmt:
			emit("go.return", typed, "", map[string]any{
				"resolution":   "syntactic",
				"result_count": len(typed.Results),
			})
		case *ast.BranchStmt:
			kind := branchObservationKind(typed.Tok)
			if kind != "" {
				label := ""
				if typed.Label != nil {
					label = typed.Label.Name
				}
				emit(kind, typed, label, map[string]any{
					"resolution":    "syntactic",
					"label_present": typed.Label != nil,
				})
			}
		case *ast.CallExpr:
			if identifier, ok := typed.Fun.(*ast.Ident); ok {
				if identifier.Name == "panic" || identifier.Name == "recover" {
					emit("go."+identifier.Name, typed, identifier.Name, map[string]any{
						"resolution":     "unresolved",
						"argument_count": len(typed.Args),
						"shadowable":     true,
					})
				}
			}
			if dynamicCallee(typed.Fun) {
				emit("go.dynamic", typed, "", map[string]any{
					"resolution":   "unknown",
					"reason":       "dynamic_callee",
					"callee_shape": expressionShape(typed.Fun),
				})
			}
		}
		return true
	})
	return observations
}

func callableNodeName(expression ast.Expr) string {
	name, _, _ := callableSyntax(expression)
	return name
}

func branchObservationKind(branch token.Token) string {
	switch branch {
	case token.BREAK:
		return "go.break"
	case token.CONTINUE:
		return "go.continue"
	case token.GOTO:
		return "go.goto"
	default:
		return ""
	}
}

func dynamicCallee(expression ast.Expr) bool {
	_, direct, selector := callableSyntax(expression)
	return !direct && !selector && !explicitTypeExpression(expression)
}
