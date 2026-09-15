package sample

import (
	alias "example.invalid/alias"
	_ "example.invalid/blank"
	. "example.invalid/dot"
)

const (
	Exported = 1
	private = 2
)

var First, Second int

type Alias = string
type Generic[T any] struct {
	Value T
}

func deferredUntilGO4() {}
