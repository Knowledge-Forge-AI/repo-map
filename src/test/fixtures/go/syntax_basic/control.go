package sample

func controlExamples(ch chan int, done <-chan int, flag bool) {
	closure := func(value int) int { return value }
	go closure(1)
	defer closure(2)
	ch <- 3
	_ = <-done
	select {
	case ch <- 4:
	case <-done:
	default:
	}
	if flag {
		panic("fixture-panic")
	}
	_ = recover()
	for {
		break
	}
	for {
		continue
	}
	goto Exit
Exit:
	_ = func() {}()
}
