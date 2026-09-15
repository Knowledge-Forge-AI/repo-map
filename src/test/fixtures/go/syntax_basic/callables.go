package sample

func Exported[T any](
	first int,
	zeta, alpha string,
	rest ...byte,
) (int, error) {
	return 0, nil
}

func private() {}

type Box[T any] struct{}

func (box *Box[T]) Transform(values []T, apply func(T) T) (out T, ok bool) {
	return out, ok
}

func (Box[T]) Value(input map[string]int) chan<- int {
	return nil
}

func (*Box[T]) Reset() {}
