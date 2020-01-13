

NAME = RawMouse

default: ../$(NAME).zip

../$(NAME).zip: *
	cd ..; zip -ur $(NAME).zip $(NAME)/* -x $(NAME)/Makefile || true