package sample

import "fmt"

type ExpressionBox[T any] struct {
	Value T
}

func expressionExamples(values []int, mapping map[string]int, input any) {
	_ = values[1]
	_ = values[1:2]
	_ = map[string]int{"fixture-key": 1}["fixture-key"]
	_ = ExpressionBox[int]{Value: 1}
	_ = []byte("fixture-value")
	_ = input.(string)
	_ = (*ExpressionBox[int]).expressionMethod
	_ = Generic[int, string]
	fmt.Println(mapping)
	switch typed := input.(type) {
	case string:
		_ = typed
	}
}

func (box *ExpressionBox[T]) expressionMethod(value T) T {
	return value
}
